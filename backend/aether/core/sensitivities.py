"""Risk-weighted sensitivity margin — quantitative function F13.

A **sensitivity-based** initial margin: bucketed delta risk is measured by
revaluation, weighted by published risk weights, and aggregated through correlation
matrices rather than summed.

.. rubric:: What this is, precisely

::

    s_k        bucketed sensitivity    PV change for a 1bp bump of curve pillar k
    WS_k       weighted sensitivity    s_k * RW_k
    K_b        bucket margin           sqrt( sum_i sum_j rho_ij WS_i WS_j )
    S_b        bucket aggregate        clamp( sum_i WS_i, -K_b, +K_b )
    IR margin                          sqrt( sum_b K_b^2 + sum_{b != c} gamma_bc S_b S_c )
    Total                              sqrt( IR^2 + FX^2 + 2 * gamma_ir_fx * IR * FX )

Sensitivities are produced by **full revaluation** — the pricing engine is called
again against a perturbed market state — not by a closed-form approximation. That
costs one repricing per bucket and removes an entire class of analytic-derivative
bugs.

.. rubric:: What this is NOT

**This is not ISDA SIMM.** SIMM is a licensed model with its own calibrated risk
weights, correlations, concentration thresholds, curvature and vega treatment, and a
governed annual recalibration. What this module shares with it is the *shape* of the
aggregation, which is public. Every risk weight and correlation below is AETHER's
own, documented at the point of use, and calibrated to nothing. Nothing here is
SIMM, SIMM-certified, SIMM-equivalent or SIMM-validated.

.. rubric:: Vega

The book contains no optionality, so vega is **zero by construction** rather than by
omission: there is no instrument in :mod:`aether.core.instruments` whose value
depends on a volatility. The aggregation carries a vega term so that adding an
option later is a pricing problem and not a margin-framework problem, and it reports
zero with that reason attached.

.. rubric:: Float discipline

Correlation products and square roots are irrational operations; no decimal
representation makes them exact. The aggregation arithmetic is therefore ``float``,
and the boundary is explicit: sensitivities arrive as :class:`~decimal.Decimal`
money, aggregation happens in ``float``, and the reported margin is quantised back
to ``Decimal`` before it becomes a cash amount.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from aether.core.exposure import compute_exposure
from aether.core.instruments import FXForward, InterestRateSwap, Portfolio
from aether.core.market import MarketSnapshot
from aether.core.money import Currency, Money, quantize_money

__all__ = [
    "FX_RISK_WEIGHT",
    "IR_RISK_WEIGHTS_BP",
    "BucketMargin",
    "RiskClass",
    "RiskMeasure",
    "Sensitivity",
    "SensitivityMarginResult",
    "compute_sensitivities",
    "compute_sensitivity_margin",
    "ir_risk_weight",
]

#: Size of the curve bump used to measure a delta sensitivity, in basis points.
#: One basis point is small enough that the local linearity assumption holds and
#: large enough that the revaluation difference is not lost in rounding.
BUMP_BP = 1.0

#: Size of the FX bump, as a relative move. One percent, for the same reason.
FX_BUMP_RELATIVE = 0.01

#: AETHER's own interest-rate risk weights, in basis points of adverse move per
#: tenor. Downward-sloping because short rates are more volatile in absolute terms
#: than long rates, which is the standard empirical shape. **Not calibrated to any
#: data set and not certified by anyone.**
IR_RISK_WEIGHTS_BP: tuple[tuple[float, Decimal], ...] = (
    (0.0833, Decimal("65")),
    (0.25, Decimal("62")),
    (0.5, Decimal("58")),
    (1.0, Decimal("54")),
    (2.0, Decimal("50")),
    (3.0, Decimal("48")),
    (5.0, Decimal("45")),
    (7.0, Decimal("43")),
    (10.0, Decimal("41")),
    (20.0, Decimal("39")),
    (30.0, Decimal("38")),
)

#: FX risk weight: the assumed adverse move, as a multiple of the 1% bump used to
#: measure the sensitivity. 7.5 means "a 7.5% adverse currency move".
FX_RISK_WEIGHT = Decimal("7.5")

#: Correlation floor between two interest-rate tenors in the same currency. The
#: matrix is built as ``phi + (1 - phi) * exp(-theta * |ln(t_i / t_j)|)``, a convex
#: combination of the all-ones matrix and an Ornstein-Uhlenbeck correlation on log
#: tenor. Both are positive semi-definite, so the combination is too — which matters,
#: because a non-PSD correlation matrix can produce a negative variance and an
#: imaginary margin. A property test asserts PSD.
_IR_TENOR_FLOOR = 0.35
_IR_TENOR_DECAY = 0.30

#: Correlation between interest-rate buckets in different currencies.
_IR_CROSS_CURRENCY = 0.27

#: Correlation between two FX exposures.
_FX_CROSS_PAIR = 0.50

#: Correlation between the interest-rate and FX risk classes.
_IR_FX = 0.28


class RiskClass(StrEnum):
    INTEREST_RATE = "INTEREST_RATE"
    FX = "FX"


class RiskMeasure(StrEnum):
    DELTA = "DELTA"
    VEGA = "VEGA"


@dataclass(frozen=True, slots=True)
class Sensitivity:
    """One bucketed sensitivity, measured by revaluation."""

    risk_class: RiskClass
    measure: RiskMeasure
    bucket: str
    label: str
    tenor_years: float | None
    value: Money
    risk_weight: Decimal
    weighted_value: Money

    @property
    def is_material(self) -> bool:
        return abs(self.value.amount) >= Decimal("0.01")


@dataclass(frozen=True, slots=True)
class BucketMargin:
    """The margin contribution of one correlated bucket."""

    risk_class: RiskClass
    bucket: str
    sensitivity_count: int
    weighted_sum: Money
    margin: Money


@dataclass(frozen=True, slots=True)
class SensitivityMarginResult:
    """Risk-weighted sensitivity margin for a netting set."""

    netting_set_id: str
    snapshot_id: str
    as_of: date
    base_currency: Currency
    sensitivities: tuple[Sensitivity, ...]
    buckets: tuple[BucketMargin, ...]
    interest_rate_margin: Money
    fx_margin: Money
    vega_margin: Money
    total_margin: Money
    method: str = "Risk-weighted sensitivity aggregation (AETHER weights, uncertified)"

    @property
    def disclaimer(self) -> str:
        return (
            "Sensitivity-based margin using AETHER's own documented risk weights and "
            "correlations. This is NOT ISDA SIMM: it is not licensed, not calibrated "
            "and not certified under any industry methodology."
        )

    @property
    def vega_note(self) -> str:
        return (
            "Vega is zero by construction: the netting set holds no optionality, so "
            "no position in it has a value that depends on a volatility."
        )

    @property
    def material_sensitivities(self) -> tuple[Sensitivity, ...]:
        return tuple(s for s in self.sensitivities if s.is_material)


def ir_risk_weight(tenor_years: float) -> Decimal:
    """Risk weight for an interest-rate tenor.

    Picks the weight of the nearest defined tenor measured in *log* space, because
    the distance from 1y to 2y matters more than the distance from 20y to 21y.
    """
    if tenor_years <= 0:
        return IR_RISK_WEIGHTS_BP[0][1]
    target = math.log(tenor_years)
    return min(IR_RISK_WEIGHTS_BP, key=lambda row: abs(math.log(row[0]) - target))[1]


def _tenor_correlation(t_i: float, t_j: float) -> float:
    """Correlation between two interest-rate tenors in the same currency."""
    if t_i <= 0 or t_j <= 0:
        return 1.0
    decay = math.exp(-_IR_TENOR_DECAY * abs(math.log(t_i / t_j)))
    return _IR_TENOR_FLOOR + (1.0 - _IR_TENOR_FLOOR) * decay


def _portfolio_currencies(portfolio: Portfolio) -> tuple[Currency, ...]:
    """Every currency the book has interest-rate exposure to, in stable order."""
    found: list[Currency] = []
    for trade in portfolio.trades:
        candidates: tuple[Currency, ...]
        match trade:
            case InterestRateSwap():
                candidates = (trade.currency,)
            case FXForward():
                candidates = (trade.buy_currency, trade.sell_currency)
        for currency in candidates:
            if currency not in found:
                found.append(currency)
    return tuple(sorted(found, key=lambda c: c.value))


def compute_sensitivities(
    portfolio: Portfolio,
    snapshot: MarketSnapshot,
    as_of: date,
    base_currency: Currency,
) -> tuple[Sensitivity, ...]:
    """Measure bucketed delta sensitivities by full revaluation.

    For every curve pillar in every currency the book touches, the curve is bumped by
    one basis point at that pillar alone, the whole netting set is repriced, and the
    difference in base-currency present value is the sensitivity. FX sensitivities
    follow the same procedure with a 1% appreciation of each non-base currency.
    """
    base_pv = compute_exposure(portfolio, snapshot, as_of, base_currency).exposure
    sensitivities: list[Sensitivity] = []

    for currency in _portfolio_currencies(portfolio):
        if currency not in snapshot.curves:
            continue
        curve = snapshot.curve(currency)
        for index, tenor in enumerate(curve.pillars_years):
            bumped = snapshot.with_curve(curve.bumped(index, BUMP_BP))
            bumped_pv = compute_exposure(portfolio, bumped, as_of, base_currency).exposure
            value = bumped_pv - base_pv
            weight = ir_risk_weight(tenor)
            sensitivities.append(
                Sensitivity(
                    risk_class=RiskClass.INTEREST_RATE,
                    measure=RiskMeasure.DELTA,
                    bucket=currency.value,
                    label=f"{currency.value} {_tenor_label(tenor)}",
                    tenor_years=tenor,
                    value=value,
                    risk_weight=weight,
                    weighted_value=Money(quantize_money(value.amount * weight), base_currency),
                )
            )

    for currency in _portfolio_currencies(portfolio):
        if currency is base_currency:
            continue
        bumped = snapshot.with_fx_bump(currency, FX_BUMP_RELATIVE)
        bumped_pv = compute_exposure(portfolio, bumped, as_of, base_currency).exposure
        value = bumped_pv - base_pv
        sensitivities.append(
            Sensitivity(
                risk_class=RiskClass.FX,
                measure=RiskMeasure.DELTA,
                bucket=f"{currency.value}/{base_currency.value}",
                label=f"{currency.value}/{base_currency.value} spot",
                tenor_years=None,
                value=value,
                risk_weight=FX_RISK_WEIGHT,
                weighted_value=Money(quantize_money(value.amount * FX_RISK_WEIGHT), base_currency),
            )
        )

    return tuple(sensitivities)


def _tenor_label(tenor: float) -> str:
    if tenor < 1:
        return f"{round(tenor * 12)}m"
    return f"{tenor:g}y"


def _bucket_margin(weighted: list[float], correlations: list[list[float]]) -> float:
    """``sqrt(w' R w)`` — the correlated aggregation of one bucket."""
    total = 0.0
    for i, w_i in enumerate(weighted):
        for j, w_j in enumerate(weighted):
            total += correlations[i][j] * w_i * w_j
    # A PSD correlation matrix cannot produce a negative quadratic form; the clamp
    # guards against accumulated floating-point error at the boundary, not against a
    # modelling mistake.
    return math.sqrt(max(total, 0.0))


def _aggregate_across_buckets(margins: list[float], aggregates: list[float], gamma: float) -> float:
    total = sum(k * k for k in margins)
    for i, s_i in enumerate(aggregates):
        for j, s_j in enumerate(aggregates):
            if i != j:
                total += gamma * s_i * s_j
    return math.sqrt(max(total, 0.0))


def compute_sensitivity_margin(
    portfolio: Portfolio,
    snapshot: MarketSnapshot,
    as_of: date,
    base_currency: Currency,
    netting_set_id: str | None = None,
) -> SensitivityMarginResult:
    """Compute risk-weighted sensitivity margin for a netting set."""
    sensitivities = compute_sensitivities(portfolio, snapshot, as_of, base_currency)

    buckets: list[BucketMargin] = []
    ir_margins: list[float] = []
    ir_aggregates: list[float] = []

    ir_buckets = _group(sensitivities, RiskClass.INTEREST_RATE)
    for bucket, members in ir_buckets:
        weighted = [float(s.weighted_value.amount) for s in members]
        tenors = [s.tenor_years or 0.0 for s in members]
        correlations = [[_tenor_correlation(t_i, t_j) for t_j in tenors] for t_i in tenors]
        margin = _bucket_margin(weighted, correlations)
        aggregate = max(-margin, min(margin, sum(weighted)))

        ir_margins.append(margin)
        ir_aggregates.append(aggregate)
        buckets.append(
            BucketMargin(
                risk_class=RiskClass.INTEREST_RATE,
                bucket=bucket,
                sensitivity_count=len(members),
                weighted_sum=Money(quantize_money(Decimal(repr(sum(weighted)))), base_currency),
                margin=Money(quantize_money(Decimal(repr(margin))), base_currency),
            )
        )

    fx_members = [s for s in sensitivities if s.risk_class is RiskClass.FX]
    fx_weighted = [float(s.weighted_value.amount) for s in fx_members]
    fx_correlations = [
        [1.0 if i == j else _FX_CROSS_PAIR for j in range(len(fx_weighted))]
        for i in range(len(fx_weighted))
    ]
    fx_total = _bucket_margin(fx_weighted, fx_correlations)
    for member, weight in zip(fx_members, fx_weighted, strict=True):
        buckets.append(
            BucketMargin(
                risk_class=RiskClass.FX,
                bucket=member.bucket,
                sensitivity_count=1,
                weighted_sum=Money(quantize_money(Decimal(repr(weight))), base_currency),
                margin=Money(quantize_money(Decimal(repr(abs(weight)))), base_currency),
            )
        )

    ir_total = _aggregate_across_buckets(ir_margins, ir_aggregates, _IR_CROSS_CURRENCY)
    total = math.sqrt(max(ir_total**2 + fx_total**2 + 2 * _IR_FX * ir_total * fx_total, 0.0))

    return SensitivityMarginResult(
        netting_set_id=netting_set_id or portfolio.netting_set_id,
        snapshot_id=snapshot.snapshot_id,
        as_of=as_of,
        base_currency=base_currency,
        sensitivities=sensitivities,
        buckets=tuple(buckets),
        interest_rate_margin=Money(quantize_money(Decimal(repr(ir_total))), base_currency),
        fx_margin=Money(quantize_money(Decimal(repr(fx_total))), base_currency),
        vega_margin=Money.zero(base_currency),
        total_margin=Money(quantize_money(Decimal(repr(total))), base_currency),
    )


def _group(
    sensitivities: tuple[Sensitivity, ...], risk_class: RiskClass
) -> list[tuple[str, list[Sensitivity]]]:
    """Group sensitivities into buckets, preserving a stable order."""
    grouped: dict[str, list[Sensitivity]] = {}
    for sensitivity in sensitivities:
        if sensitivity.risk_class is not risk_class:
            continue
        grouped.setdefault(sensitivity.bucket, []).append(sensitivity)
    return sorted(grouped.items())
