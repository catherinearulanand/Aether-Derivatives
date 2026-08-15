"""FX forward valuation — quantitative function F3.

An outright forward to buy ``N`` units of the buy currency and sell ``N * K`` units
of the sell currency at maturity ``T``.

.. rubric:: The maths

Value the two legs separately and net them in the sell currency:

- Receiving ``N`` of the buy currency at ``T`` is worth ``N * DF_buy(T)`` in buy
  currency, or ``N * DF_buy(T) * S`` in sell currency, where ``S`` is spot expressed
  as units of sell per one unit of buy.
- Paying ``N * K`` of the sell currency at ``T`` is worth ``N * K * DF_sell(T)``.

So::

    PV_sell_ccy = N * DF_buy(T) * S  -  N * K * DF_sell(T)

The market forward rate follows from covered interest parity, ``F(T) = S *
DF_buy(T) / DF_sell(T)``, and substituting it gives the equivalent form
``PV = N * (F(T) - K) * DF_sell(T)``. Both are implemented; they agree to within
floating-point noise, and that agreement is asserted by a test.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from aether.core.curves import year_fraction
from aether.core.instruments import FXForward
from aether.core.market import MarketSnapshot
from aether.core.money import Money, quantize_money

__all__ = ["FXForwardValuation", "forward_rate", "price_fx_forward"]


@dataclass(frozen=True, slots=True)
class FXForwardValuation:
    """Valuation detail, expressed in the forward's sell currency."""

    present_value: Money
    market_forward_rate: Decimal
    contract_rate: Decimal
    years_to_maturity: float


def forward_rate(forward: FXForward, snapshot: MarketSnapshot, as_of: date) -> float:
    """Covered-interest-parity forward rate, in sell-currency units per buy-currency unit."""
    t = year_fraction(as_of, forward.maturity_date)
    spot = float(snapshot.fx_rate(forward.buy_currency, forward.sell_currency))
    df_buy = snapshot.curve(forward.buy_currency).discount_factor(t)
    df_sell = snapshot.curve(forward.sell_currency).discount_factor(t)
    return spot * df_buy / df_sell


def price_fx_forward(
    forward: FXForward,
    snapshot: MarketSnapshot,
    as_of: date,
) -> FXForwardValuation:
    """Present value of ``forward`` on ``as_of``, in the sell currency."""
    if snapshot.as_of != as_of:
        raise ValueError(
            f"Snapshot as_of {snapshot.as_of} does not match valuation date {as_of}. "
            "Every calculation takes an explicit as_of and a pinned snapshot."
        )

    t = year_fraction(as_of, forward.maturity_date)

    if t <= 0:
        return FXForwardValuation(
            present_value=Money.zero(forward.sell_currency),
            market_forward_rate=Decimal(0),
            contract_rate=forward.strike,
            years_to_maturity=0.0,
        )

    spot = float(snapshot.fx_rate(forward.buy_currency, forward.sell_currency))
    df_buy = snapshot.curve(forward.buy_currency).discount_factor(t)
    df_sell = snapshot.curve(forward.sell_currency).discount_factor(t)

    notional = float(forward.buy_notional)
    strike = float(forward.strike)

    pv = notional * df_buy * spot - notional * strike * df_sell

    return FXForwardValuation(
        present_value=Money(quantize_money(Decimal(repr(pv))), forward.sell_currency),
        market_forward_rate=quantize_money(Decimal(repr(spot * df_buy / df_sell))),
        contract_rate=forward.strike,
        years_to_maturity=t,
    )
