"""Initial margin — quantitative function F7, standardised schedule only.

.. rubric:: What this is, precisely

This implements the **BCBS-IOSCO standardised initial margin schedule** for
non-centrally-cleared derivatives: a published grid of percentages applied to gross
notional by asset class and maturity band, then adjusted for netting.

::

    GrossIM = sum over trades of  notional * schedule_rate(asset_class, maturity)
    NetIM   = (0.4 + 0.6 * NGR) * GrossIM

where ``NGR`` is the net-to-gross ratio — net replacement cost over gross replacement
cost — which gives partial credit for netting within the set.

.. rubric:: What this is NOT

**This is not ISDA SIMM.** SIMM is a sensitivity-based model with six risk classes,
curvature, vega and concentration thresholds, and it is licensed. Nothing here should
ever be described as SIMM, SIMM-certified, or SIMM-equivalent. The schedule approach
is deliberately chosen because it is fully public, implementable exactly, and
verifiable by anyone with the BCBS-IOSCO framework in front of them.

The schedule is conservative by design — it will generally produce a larger number
than a sensitivity-based model would. That is a property of the standard, not a bug.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aether.core.curves import year_fraction
from aether.core.exposure import ExposureResult
from aether.core.instruments import FXForward, InterestRateSwap, Portfolio, Trade
from aether.core.market import MarketSnapshot
from aether.core.money import Currency, Money, quantize_money

__all__ = [
    "SCHEDULE_RATES",
    "InitialMarginResult",
    "TradeMarginCharge",
    "compute_schedule_im",
    "schedule_rate",
]

#: BCBS-IOSCO standardised schedule, as a fraction of notional.
#: Keyed by (asset class, maturity band). Bands are 0-2y, 2-5y, 5y+.
SCHEDULE_RATES: tuple[tuple[str, str, Decimal], ...] = (
    ("INTEREST_RATE", "0-2y", Decimal("0.01")),
    ("INTEREST_RATE", "2-5y", Decimal("0.02")),
    ("INTEREST_RATE", "5y+", Decimal("0.04")),
    ("FX", "any", Decimal("0.06")),
    ("CREDIT", "0-2y", Decimal("0.02")),
    ("CREDIT", "2-5y", Decimal("0.05")),
    ("CREDIT", "5y+", Decimal("0.10")),
    ("EQUITY", "any", Decimal("0.15")),
    ("COMMODITY", "any", Decimal("0.15")),
    ("OTHER", "any", Decimal("0.15")),
)

#: Floor on the netting benefit. A netting set never gets more than 60% relief.
_NGR_FLOOR = Decimal("0.4")
_NGR_WEIGHT = Decimal("0.6")


def maturity_band(years: float) -> str:
    if years < 2:
        return "0-2y"
    if years <= 5:
        return "2-5y"
    return "5y+"


def schedule_rate(asset_class: str, years: float) -> Decimal:
    """Look up the standardised rate for an asset class and remaining maturity."""
    band = maturity_band(years)
    for cls, cls_band, rate in SCHEDULE_RATES:
        if cls == asset_class and cls_band in (band, "any"):
            return rate
    raise KeyError(f"No schedule rate for asset class '{asset_class}'.")


@dataclass(frozen=True, slots=True)
class TradeMarginCharge:
    """One trade's gross schedule charge."""

    trade_id: str
    asset_class: str
    notional: Money
    years_to_maturity: float
    band: str
    rate: Decimal
    charge: Money


@dataclass(frozen=True, slots=True)
class InitialMarginResult:
    """Standardised schedule initial margin for a netting set."""

    netting_set_id: str
    snapshot_id: str
    base_currency: Currency
    gross_im: Money
    net_to_gross_ratio: Decimal
    initial_margin: Money
    charges: tuple[TradeMarginCharge, ...]
    method: str = "BCBS-IOSCO standardised schedule"

    @property
    def disclaimer(self) -> str:
        return (
            "Standardised schedule initial margin. This is not ISDA SIMM and is not "
            "certified under any industry methodology."
        )


def _classify(trade: Trade) -> str:
    match trade:
        case InterestRateSwap():
            return "INTEREST_RATE"
        case FXForward():
            return "FX"


def compute_schedule_im(
    portfolio: Portfolio,
    exposure_result: ExposureResult,
    snapshot: MarketSnapshot,
    base_currency: Currency,
) -> InitialMarginResult:
    """Compute standardised schedule IM for a netting set.

    Notionals are converted to the base currency at the snapshot's spot rates, and
    the netting benefit uses the net-to-gross ratio already computed by the exposure
    engine, so IM and exposure are always consistent with each other.
    """
    charges: list[TradeMarginCharge] = []
    gross = Money.zero(base_currency)

    for trade in portfolio.trades:
        asset_class = _classify(trade)
        years = year_fraction(snapshot.as_of, trade.maturity_date)
        years = max(years, 0.0)

        match trade:
            case InterestRateSwap():
                notional_native = Money(trade.notional, trade.currency)
            case FXForward():
                notional_native = Money(trade.buy_notional, trade.buy_currency)

        notional_base = snapshot.convert(notional_native, base_currency)
        rate = schedule_rate(asset_class, years)
        charge = Money(quantize_money(notional_base.amount * rate), base_currency)

        charges.append(
            TradeMarginCharge(
                trade_id=trade.trade_id,
                asset_class=asset_class,
                notional=notional_base,
                years_to_maturity=years,
                band=maturity_band(years),
                rate=rate,
                charge=charge,
            )
        )
        gross = gross + charge

    # Net-to-gross ratio from replacement cost, floored into [0, 1].
    gross_positive = exposure_result.gross_positive
    if gross_positive.is_zero:
        ngr = Decimal(0)
    else:
        net_replacement = exposure_result.exposure.max_with_zero()
        ngr = net_replacement.amount / gross_positive.amount
        ngr = max(Decimal(0), min(Decimal(1), ngr))

    multiplier = _NGR_FLOOR + _NGR_WEIGHT * ngr
    net_im = Money(quantize_money(gross.amount * multiplier), base_currency)

    return InitialMarginResult(
        netting_set_id=exposure_result.netting_set_id,
        snapshot_id=exposure_result.snapshot_id,
        base_currency=base_currency,
        gross_im=gross,
        net_to_gross_ratio=quantize_money(ngr),
        initial_margin=net_im,
        charges=tuple(charges),
    )
