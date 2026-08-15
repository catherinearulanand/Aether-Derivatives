"""Netting-set exposure — quantitative function F5.

Exposure is the sum of trade present values across a single netting set, converted
to the CSA base currency at the snapshot's spot rates.

The netting rule is the point of this module. Under an ISDA Master Agreement,
positive and negative mark-to-market values offset **only within** the netting set
that Master defines. Netting across Masters would overstate the benefit and
understate real exposure. :class:`~aether.core.instruments.Portfolio` refuses to hold
mixed netting sets, and this module re-checks against the agreement it is asked to
value under, so the rule holds even if a caller assembles inputs by hand.

Sign convention, fixed once here and relied on downstream:

    **Positive exposure means the counterparty owes us** — we are in the money and
    carry credit risk to them. Negative exposure means we owe them.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aether.core.instruments import FXForward, InterestRateSwap, Portfolio, Trade
from aether.core.market import MarketSnapshot
from aether.core.money import Currency, Money
from aether.core.pricing.fx_forward import price_fx_forward
from aether.core.pricing.irs import price_swap

__all__ = ["ExposureResult", "TradeValuation", "compute_exposure", "price_trade"]


@dataclass(frozen=True, slots=True)
class TradeValuation:
    """One trade's contribution to exposure, in both native and base currency."""

    trade_id: str
    trade_type: str
    native_value: Money
    base_value: Money
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExposureResult:
    """Netting-set exposure and the per-trade breakdown behind it.

    Carries ``snapshot_id``, ``as_of`` and ``netting_set_id`` so the figure can never
    be separated from the market state and legal scope that produced it.
    """

    netting_set_id: str
    snapshot_id: str
    as_of: date
    base_currency: Currency
    exposure: Money
    trade_valuations: tuple[TradeValuation, ...]

    @property
    def trade_count(self) -> int:
        return len(self.trade_valuations)

    @property
    def gross_positive(self) -> Money:
        """Sum of in-the-money trades — what exposure would be with no netting."""
        total = Money.zero(self.base_currency)
        for valuation in self.trade_valuations:
            if valuation.base_value.is_positive:
                total = total + valuation.base_value
        return total

    @property
    def netting_benefit(self) -> Money:
        """Reduction in exposure attributable to netting within this set."""
        return self.gross_positive - self.exposure


def price_trade(
    trade: Trade,
    snapshot: MarketSnapshot,
    as_of: date,
    base_currency: Currency,
) -> TradeValuation:
    """Value one trade and express it in both native and base currency."""
    match trade:
        case InterestRateSwap():
            legs = price_swap(trade, snapshot.curve(trade.currency), as_of)
            native = legs.present_value
            detail = (
                f"{trade.direction.value.replace('_', ' ').lower()}, "
                f"{legs.remaining_periods} periods remaining"
            )
            trade_type = "INTEREST_RATE_SWAP"

        case FXForward():
            valuation = price_fx_forward(trade, snapshot, as_of)
            native = valuation.present_value
            detail = f"forward {valuation.market_forward_rate} vs strike {valuation.contract_rate}"
            trade_type = "FX_FORWARD"

        case _:  # pragma: no cover - the union is closed
            raise TypeError(f"Cannot price {type(trade).__name__}.")

    return TradeValuation(
        trade_id=trade.trade_id,
        trade_type=trade_type,
        native_value=native,
        base_value=snapshot.convert(native, base_currency),
        detail=detail,
    )


def compute_exposure(
    portfolio: Portfolio,
    snapshot: MarketSnapshot,
    as_of: date,
    base_currency: Currency,
    netting_set_id: str | None = None,
) -> ExposureResult:
    """Compute netted exposure for ``portfolio`` under ``snapshot``.

    ``netting_set_id``, when supplied, is the netting set of the agreement being
    valued under. A mismatch raises: valuing a portfolio against the wrong Master
    Agreement is a correctness failure, not a warning.
    """
    if snapshot.as_of != as_of:
        raise ValueError(
            f"Snapshot {snapshot.snapshot_id} is as of {snapshot.as_of}, but the "
            f"valuation date is {as_of}. Pin the snapshot to the valuation date."
        )
    if netting_set_id is not None and netting_set_id != portfolio.netting_set_id:
        raise ValueError(
            f"Portfolio {portfolio.portfolio_id} belongs to netting set "
            f"{portfolio.netting_set_id}, but was valued under agreement netting set "
            f"{netting_set_id}. Trades under different Master Agreements must never net."
        )

    valuations = tuple(
        price_trade(trade, snapshot, as_of, base_currency) for trade in portfolio.trades
    )

    total = Money.zero(base_currency)
    for valuation in valuations:
        total = total + valuation.base_value

    return ExposureResult(
        netting_set_id=portfolio.netting_set_id,
        snapshot_id=snapshot.snapshot_id,
        as_of=as_of,
        base_currency=base_currency,
        exposure=total,
        trade_valuations=valuations,
    )
