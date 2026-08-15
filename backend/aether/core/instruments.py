"""Trade definitions and netting sets.

Two instrument types are modelled: the vanilla interest rate swap and the FX forward.
Both are closed-form and defensible; neither hides a modelling choice a reviewer
cannot check.

The netting set is enforced structurally. A :class:`Portfolio` refuses to hold trades
from more than one netting set, so the "trades under different Master Agreements must
never offset" rule cannot be violated by a caller who forgets — it fails at
construction.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from aether.core.money import Currency

__all__ = [
    "FXForward",
    "InterestRateSwap",
    "Portfolio",
    "SwapDirection",
    "Trade",
]


class SwapDirection(StrEnum):
    """Which leg of the swap this party pays.

    ``PAY_FIXED`` gains value when rates rise; ``RECEIVE_FIXED`` loses value when
    rates rise. This sign convention is the source of the demo's collateral call,
    so it is worth being unambiguous about.
    """

    PAY_FIXED = "PAY_FIXED"
    RECEIVE_FIXED = "RECEIVE_FIXED"


@dataclass(frozen=True, slots=True)
class InterestRateSwap:
    """A vanilla fixed-for-floating interest rate swap.

    Both legs share a schedule and a notional. The floating leg projects off the same
    curve used for discounting — the single-curve simplification documented in
    :mod:`aether.core.curves`.
    """

    trade_id: str
    netting_set_id: str
    notional: Decimal
    currency: Currency
    direction: SwapDirection
    fixed_rate: Decimal
    payment_frequency_months: int
    effective_date: date
    maturity_date: date
    float_index: str = ""

    def __post_init__(self) -> None:
        if self.notional <= 0:
            raise ValueError(f"{self.trade_id}: notional must be positive.")
        if self.maturity_date <= self.effective_date:
            raise ValueError(
                f"{self.trade_id}: maturity {self.maturity_date} must follow "
                f"effective date {self.effective_date}."
            )
        if self.payment_frequency_months <= 0 or 12 % self.payment_frequency_months != 0:
            raise ValueError(
                f"{self.trade_id}: payment frequency must divide 12 months, "
                f"got {self.payment_frequency_months}."
            )


@dataclass(frozen=True, slots=True)
class FXForward:
    """An outright FX forward: buy ``buy_notional`` of one currency, sell another.

    ``strike`` is quoted as units of ``sell_currency`` per one unit of
    ``buy_currency``, matching the fixture convention.
    """

    trade_id: str
    netting_set_id: str
    buy_currency: Currency
    buy_notional: Decimal
    sell_currency: Currency
    strike: Decimal
    maturity_date: date

    def __post_init__(self) -> None:
        if self.buy_notional <= 0:
            raise ValueError(f"{self.trade_id}: notional must be positive.")
        if self.strike <= 0:
            raise ValueError(f"{self.trade_id}: strike must be positive.")
        if self.buy_currency is self.sell_currency:
            raise ValueError(
                f"{self.trade_id}: buy and sell currency are both {self.buy_currency}."
            )


#: A priced instrument. Kept as a union rather than a base class so exhaustive
#: matching in the pricer is checkable rather than dependent on runtime dispatch.
Trade = InterestRateSwap | FXForward


@dataclass(frozen=True, slots=True)
class Portfolio:
    """Trades under a single netting set.

    The single-netting-set rule is enforced here, at construction, because it is a
    correctness property rather than a convention: netting across Master Agreements
    would overstate netting benefit and understate exposure.
    """

    portfolio_id: str
    netting_set_id: str
    trades: tuple[Trade, ...]
    book_owner: str = "PARTY_A"

    def __post_init__(self) -> None:
        if not self.trades:
            raise ValueError(f"Portfolio {self.portfolio_id} contains no trades.")

        foreign = sorted(
            {t.netting_set_id for t in self.trades if t.netting_set_id != self.netting_set_id}
        )
        if foreign:
            raise ValueError(
                f"Portfolio {self.portfolio_id} declares netting set "
                f"{self.netting_set_id} but contains trades from {foreign}. "
                "Trades under different Master Agreements must never be netted."
            )

        counts = Counter(t.trade_id for t in self.trades)
        duplicates = sorted(trade_id for trade_id, n in counts.items() if n > 1)
        if duplicates:
            raise ValueError(
                f"Portfolio {self.portfolio_id} has duplicate trade ids: {duplicates}."
            )

    def __len__(self) -> int:
        return len(self.trades)
