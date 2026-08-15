"""Collateral optimization — quantitative function F9.

The commercial thesis of the product, expressed as a linear program.

.. rubric:: The problem

Given a margin call requiring ``R`` of post-haircut value, and an inventory of assets
each with a market value, an effective valuation percentage and a funding cost,
choose how much of each asset to post so that total cost is minimised and every
contractual constraint holds.

.. rubric:: The formulation

Let ``x_a`` be the market value of asset *a* to post, **expressed in the base
currency**. Working in base-currency market value keeps the algebra clean: the FX
conversion sits in ``x_a`` and the FX haircut sits in the effective percentage, so
they never get confused with one another.

::

    minimise    sum over a of  cost_a * x_a
    subject to  sum over a of  eff_a * x_a  >=  R          (coverage)
                0 <= x_a <= available_a                    (inventory)
                x_a = 0 for ineligible a                   (eligibility)
                sum over a in S of eff_a * x_a
                    <= limit_S * sum over all a of eff_a * x_a    (concentration)

The concentration constraints are stated relative to the **Value of the Credit
Support Balance**, which is the post-haircut total and is itself a decision variable.
Rearranged as ``sum_S eff_a x_a - limit_S * sum_all eff_a x_a <= 0`` the constraint
is linear, so the whole problem stays an LP and solves exactly.

.. rubric:: Why the cheapest asset is not always chosen

The ranking that matters is **cost per effective unit**::

    cost_per_effective_unit = funding_spread_bps / effective_percentage

An asset with a 9bp funding spread and an 86.48% effective valuation costs 10.41bp
per unit of collateral value actually delivered, which is worse than a 12bp asset
valued at 98%. The optimizer prices that drag; a human eyeballing headline spreads
does not.

.. rubric:: Shadow prices

The LP dual on each binding constraint is the marginal cost of that constraint — how
much total funding cost would fall if the constraint were relaxed by one unit. That
is what turns "here is an allocation" into "here is what your concentration cap is
costing you", and it comes free from the solver.

Part of the deterministic core: no I/O, no clock, no framework dependency.
NumPy and SciPy are permitted here; both are deterministic given identical input.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import numpy as np
from scipy.optimize import linprog

from aether.core.collateral import CollateralAsset, CollateralInventory
from aether.core.csa_terms import AssetClass, ConcentrationScope, CSATerms, IssuerType
from aether.core.haircut import assess_eligibility
from aether.core.market import MarketSnapshot
from aether.core.money import Currency, Money, quantize_money

__all__ = [
    "AllocationLine",
    "ConstraintShadowPrice",
    "OptimizationResult",
    "OptimizerStatus",
    "cash_first_baseline",
    "optimize_collateral",
]

#: Basis points per unit. Cost figures are annualised.
_BPS = Decimal(10_000)

#: Solver tolerance when reporting whether a constraint binds.
_BINDING_TOLERANCE = 1e-6


class OptimizerStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    NOT_REQUIRED = "NOT_REQUIRED"


@dataclass(frozen=True, slots=True)
class AllocationLine:
    """One asset's contribution to a proposed collateral allocation.

    Also used to describe an asset that was *considered and not used*, in which case
    ``selected`` is false and ``not_selected_reason`` says why. "Why was this one
    chosen and that one not?" is a question a collateral desk asks every day, and an
    optimizer that cannot answer it is a black box.
    """

    asset_id: str
    description: str
    asset_class: AssetClass
    issuer: str
    currency: Currency
    market_value_posted: Money
    effective_percentage: Decimal
    effective_value: Money
    funding_spread_bps: Decimal
    cost_per_effective_unit_bps: Decimal
    annual_cost: Money
    fx_haircut_applied: bool
    #: Cost per effective unit attributable to the FX haircut alone — the price of
    #: posting cross-border collateral, isolated from the schedule valuation.
    fx_drag_bps: Decimal = Decimal(0)
    #: Rank by headline funding spread (1 = cheapest on paper).
    headline_rank: int = 0
    #: Rank by cost per effective unit (1 = genuinely cheapest to deliver).
    effective_rank: int = 0
    available_market_value: Money | None = None
    selected: bool = True
    not_selected_reason: str = ""


@dataclass(frozen=True, slots=True)
class ConstraintShadowPrice:
    """The marginal cost of one binding constraint."""

    name: str
    description: str
    shadow_price_bps: Decimal
    binding: bool


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """A solved allocation, with the baseline it is measured against."""

    agreement_id: str
    snapshot_id: str
    base_currency: Currency
    status: OptimizerStatus
    required_value: Money
    allocated_value: Money
    lines: tuple[AllocationLine, ...]
    total_cost: Money
    baseline_cost: Money
    baseline_lines: tuple[AllocationLine, ...]
    shadow_prices: tuple[ConstraintShadowPrice, ...]
    excluded: tuple[tuple[str, str], ...]
    message: str = ""
    #: Every eligible asset, selected or not, each carrying its ranking and — when
    #: it went unused — the reason.
    considered: tuple[AllocationLine, ...] = ()
    #: Did the cash-first heuristic actually cover the requirement? If it did not,
    #: its cost is not a like-for-like comparator and the saving is withheld rather
    #: than quoted against an allocation that would not have settled.
    baseline_covers: bool = True

    @property
    def saving(self) -> Money:
        if not self.baseline_covers:
            return Money.zero(self.base_currency)
        return self.baseline_cost - self.total_cost

    @property
    def saving_percentage(self) -> Decimal:
        if not self.baseline_covers or self.baseline_cost.is_zero:
            return Decimal(0)
        return quantize_money(self.saving.amount / self.baseline_cost.amount * 100)

    @property
    def cross_border_lines(self) -> tuple[AllocationLine, ...]:
        """Considered assets denominated outside the base currency.

        This is where the cross-border collateral argument lives: a funding
        advantage in the home market, set against an FX haircut that reduces how
        much of the asset actually counts as collateral.
        """
        return tuple(line for line in self.considered if line.fx_haircut_applied)

    @property
    def is_feasible(self) -> bool:
        return self.status is not OptimizerStatus.INFEASIBLE

    @property
    def binding_constraints(self) -> tuple[ConstraintShadowPrice, ...]:
        return tuple(s for s in self.shadow_prices if s.binding)


@dataclass(frozen=True, slots=True)
class _Candidate:
    """An eligible asset, pre-converted into base-currency terms for the LP."""

    asset: CollateralAsset
    effective_percentage: Decimal
    valuation_percentage: Decimal
    fx_haircut_applied: bool
    available_base: Decimal
    cost_rate: Decimal

    @property
    def cost_per_effective_unit(self) -> Decimal:
        return self.asset.funding_spread_bps / self.effective_percentage

    @property
    def fx_drag_bps(self) -> Decimal:
        """Cost per effective unit caused by the FX haircut alone.

        The difference between what this asset costs to deliver as it stands and
        what it would cost if it were denominated in the base currency. Zero for a
        base-currency asset, by construction.
        """
        if not self.fx_haircut_applied or self.valuation_percentage <= 0:
            return Decimal(0)
        without_fx = self.asset.funding_spread_bps / self.valuation_percentage
        return self.cost_per_effective_unit - without_fx


def _build_candidates(
    inventory: CollateralInventory,
    terms: CSATerms,
    snapshot: MarketSnapshot,
) -> tuple[list[_Candidate], list[tuple[str, str]]]:
    """Filter the inventory to eligible assets, converted to base currency."""
    candidates: list[_Candidate] = []
    excluded: list[tuple[str, str]] = []

    for asset in inventory.assets:
        assessment = assess_eligibility(asset, terms)
        if not assessment.eligible:
            excluded.append((asset.asset_id, assessment.reason))
            continue

        available_base = snapshot.convert(asset.available, terms.base_currency).amount
        if available_base <= 0:
            excluded.append((asset.asset_id, "No available quantity."))
            continue

        candidates.append(
            _Candidate(
                asset=asset,
                effective_percentage=assessment.effective_percentage,
                valuation_percentage=assessment.valuation_percentage,
                fx_haircut_applied=assessment.fx_haircut_applied,
                available_base=available_base,
                cost_rate=asset.funding_spread_bps / _BPS,
            )
        )

    return candidates, excluded


#: Which asset class each class-level concentration scope caps.
_SCOPE_CLASS: tuple[tuple[ConcentrationScope, AssetClass], ...] = (
    (ConcentrationScope.CORPORATE_BOND, AssetClass.CORPORATE_BOND),
    (ConcentrationScope.EQUITY, AssetClass.EQUITY),
    (ConcentrationScope.GOLD, AssetClass.GOLD),
)


def _scope_members(candidates: list[_Candidate], scope: ConcentrationScope) -> list[int]:
    """Indices of the candidates a concentration scope applies to."""
    for scope_name, asset_class in _SCOPE_CLASS:
        if scope is scope_name:
            return [i for i, c in enumerate(candidates) if c.asset.asset_class is asset_class]
    return []


def _build_constraints(
    candidates: list[_Candidate],
    terms: CSATerms,
    required: Decimal,
) -> tuple[list[list[float]], list[float], list[tuple[str, str]]]:
    """Assemble the inequality rows for coverage and concentration."""
    n = len(candidates)
    eff = [float(c.effective_percentage) for c in candidates]

    rows: list[list[float]] = []
    rhs: list[float] = []
    labels: list[tuple[str, str]] = []

    # Coverage, written as a <= row: -sum(eff * x) <= -required.
    rows.append([-e for e in eff])
    rhs.append(-float(required))
    labels.append(("coverage", "Post-haircut value must meet the Delivery Amount"))

    # Class-level concentration caps.
    for scope, _ in _SCOPE_CLASS:
        limit = terms.concentration_limit(scope)
        if limit is None:
            continue
        members = _scope_members(candidates, scope)
        if not members:
            continue
        row = [-float(limit) * e for e in eff]
        for i in members:
            row[i] += eff[i]
        rows.append(row)
        rhs.append(0.0)
        labels.append(
            (
                f"concentration:{scope.value}",
                f"{scope.value.replace('_', ' ').title()} capped at {limit:.0%} "
                f"of the Credit Support Balance",
            )
        )

    # Per-issuer cap, applied to every non-sovereign issuer present.
    issuer_limit = terms.concentration_limit(ConcentrationScope.SINGLE_NON_SOVEREIGN_ISSUER)
    if issuer_limit is not None:
        issuers = sorted(
            {c.asset.issuer for c in candidates if c.asset.issuer_type is not IssuerType.SOVEREIGN}
        )
        for issuer in issuers:
            members = [i for i, c in enumerate(candidates) if c.asset.issuer == issuer]
            row = [-float(issuer_limit) * e for e in eff]
            for i in members:
                row[i] += eff[i]
            rows.append(row)
            rhs.append(0.0)
            labels.append(
                (
                    f"issuer:{issuer}",
                    f"Single issuer {issuer} capped at {issuer_limit:.0%} "
                    f"of the Credit Support Balance",
                )
            )

    assert all(len(r) == n for r in rows)
    return rows, rhs, labels


def _rankings(candidates: list[_Candidate]) -> tuple[dict[str, int], dict[str, int]]:
    """Rank every candidate by headline spread and by cost per effective unit.

    The two orderings disagree whenever a haircut is material, and that disagreement
    is the whole argument for having an optimizer at all.
    """
    by_headline = sorted(candidates, key=lambda c: (c.asset.funding_spread_bps, c.asset.asset_id))
    by_effective = sorted(candidates, key=lambda c: (c.cost_per_effective_unit, c.asset.asset_id))
    return (
        {c.asset.asset_id: i for i, c in enumerate(by_headline, start=1)},
        {c.asset.asset_id: i for i, c in enumerate(by_effective, start=1)},
    )


def _line_from(
    candidate: _Candidate,
    posted_base: Decimal,
    base: Currency,
    snapshot: MarketSnapshot,
    *,
    headline_rank: int = 0,
    effective_rank: int = 0,
    selected: bool = True,
    not_selected_reason: str = "",
) -> AllocationLine:
    effective = quantize_money(posted_base * candidate.effective_percentage)
    cost = quantize_money(posted_base * candidate.cost_rate)

    # Report the posted amount in the asset's own currency as well as the base.
    native = snapshot.convert(Money(posted_base, base), candidate.asset.currency)
    available = snapshot.convert(Money(candidate.available_base, base), candidate.asset.currency)

    return AllocationLine(
        asset_id=candidate.asset.asset_id,
        description=candidate.asset.description,
        asset_class=candidate.asset.asset_class,
        issuer=candidate.asset.issuer,
        currency=candidate.asset.currency,
        market_value_posted=native,
        effective_percentage=candidate.effective_percentage,
        effective_value=Money(effective, base),
        funding_spread_bps=candidate.asset.funding_spread_bps,
        cost_per_effective_unit_bps=quantize_money(candidate.cost_per_effective_unit),
        annual_cost=Money(cost, base),
        fx_haircut_applied=candidate.fx_haircut_applied,
        fx_drag_bps=quantize_money(candidate.fx_drag_bps),
        headline_rank=headline_rank,
        effective_rank=effective_rank,
        available_market_value=available,
        selected=selected,
        not_selected_reason=not_selected_reason,
    )


def _binding_scopes(shadow: list[ConstraintShadowPrice]) -> set[str]:
    return {s.name for s in shadow if s.binding and s.name != "coverage"}


def _not_selected_reason(
    candidate: _Candidate,
    binding: set[str],
    marginal_cost: Decimal | None,
) -> str:
    """Why an eligible asset was not used.

    Answered from the solved problem rather than guessed: either a cap that applies
    to this asset is binding, or the asset is simply more expensive per unit of
    collateral actually delivered than everything that filled the requirement.
    """
    asset = candidate.asset
    if f"issuer:{asset.issuer}" in binding:
        return f"Single-issuer concentration cap on {asset.issuer} is binding."
    if asset.asset_class is AssetClass.CORPORATE_BOND and "concentration:CORPORATE_BOND" in binding:
        return "Corporate bond concentration cap is binding."
    if asset.asset_class is AssetClass.EQUITY and "concentration:EQUITY" in binding:
        return "Equity concentration cap is binding."
    if asset.asset_class is AssetClass.GOLD and "concentration:GOLD" in binding:
        return "Gold concentration cap is binding."
    if marginal_cost is not None and candidate.cost_per_effective_unit > marginal_cost:
        return (
            f"Costs {candidate.cost_per_effective_unit:.2f}bp per effective unit "
            f"against {marginal_cost:.2f}bp for the most expensive asset used. The "
            f"requirement was met more cheaply."
        )
    return "Not required: the Delivery Amount was covered by cheaper eligible assets."


def cash_first_baseline(
    candidates: list[_Candidate],
    required: Decimal,
    base: Currency,
    snapshot: MarketSnapshot,
) -> tuple[list[AllocationLine], Decimal, bool]:
    """The naive desk heuristic the optimizer is measured against.

    Exhaust cash, then post sovereigns in ascending maturity, ignoring cost entirely.
    This is what a collateral desk without an optimizer actually does, and it is
    expensive precisely because cash carries the highest opportunity cost.

    Concentration caps are not consulted — the heuristic posts cash and government
    bonds, which no cap in this agreement restricts.

    Returns ``(lines, cost, covered)``. ``covered`` is false when cash and sovereigns
    alone cannot meet the requirement, in which case the heuristic's cost is *not* a
    like-for-like comparator: it is the cost of an allocation that would not have
    settled, and quoting a saving against it would overstate the result.
    """

    def sort_key(c: _Candidate) -> tuple[int, float]:
        if c.asset.asset_class is AssetClass.CASH:
            return (0, 0.0)
        if c.asset.asset_class is AssetClass.SOVEREIGN_BOND:
            return (1, float(c.asset.remaining_maturity_years or 0))
        if c.asset.asset_class is AssetClass.CORPORATE_BOND:
            return (2, float(c.asset.remaining_maturity_years or 0))
        return (3, 0.0)

    lines: list[AllocationLine] = []
    total_cost = Decimal(0)
    remaining = required

    for candidate in sorted(candidates, key=sort_key):
        if remaining <= 0:
            break
        # How much market value is needed to cover the shortfall?
        needed_mv = remaining / candidate.effective_percentage
        posted = min(needed_mv, candidate.available_base)
        if posted <= 0:
            continue

        lines.append(_line_from(candidate, posted, base, snapshot))
        total_cost += posted * candidate.cost_rate
        remaining -= posted * candidate.effective_percentage

    return lines, quantize_money(total_cost), remaining <= 0


def optimize_collateral(
    terms: CSATerms,
    inventory: CollateralInventory,
    snapshot: MarketSnapshot,
    required: Money,
) -> OptimizationResult:
    """Solve for the cheapest eligible allocation covering ``required``.

    ``required`` is the post-haircut value that must be delivered — the Delivery
    Amount from :func:`aether.core.csa.compute_margin_call`.
    """
    base = terms.base_currency
    if required.currency is not base:
        raise ValueError(f"Required amount must be in {base}, got {required.currency}.")

    candidates, excluded = _build_candidates(inventory, terms, snapshot)

    if required.amount <= 0:
        return OptimizationResult(
            agreement_id=terms.agreement_id,
            snapshot_id=snapshot.snapshot_id,
            base_currency=base,
            status=OptimizerStatus.NOT_REQUIRED,
            required_value=required,
            allocated_value=Money.zero(base),
            lines=(),
            total_cost=Money.zero(base),
            baseline_cost=Money.zero(base),
            baseline_lines=(),
            shadow_prices=(),
            excluded=tuple(excluded),
            message="No collateral is required, so nothing was allocated.",
        )

    if not candidates:
        return OptimizationResult(
            agreement_id=terms.agreement_id,
            snapshot_id=snapshot.snapshot_id,
            base_currency=base,
            status=OptimizerStatus.INFEASIBLE,
            required_value=required,
            allocated_value=Money.zero(base),
            lines=(),
            total_cost=Money.zero(base),
            baseline_cost=Money.zero(base),
            baseline_lines=(),
            shadow_prices=(),
            excluded=tuple(excluded),
            message="No eligible assets are available under this agreement.",
        )

    objective = [float(c.cost_rate) for c in candidates]
    bounds = [(0.0, float(c.available_base)) for c in candidates]
    rows, rhs, labels = _build_constraints(candidates, terms, required.amount)

    solution = linprog(
        c=np.array(objective, dtype=float),
        A_ub=np.array(rows, dtype=float),
        b_ub=np.array(rhs, dtype=float),
        bounds=bounds,
        method="highs",
    )

    if not solution.success:
        headroom = sum((c.available_base * c.effective_percentage for c in candidates), Decimal(0))
        return OptimizationResult(
            agreement_id=terms.agreement_id,
            snapshot_id=snapshot.snapshot_id,
            base_currency=base,
            status=OptimizerStatus.INFEASIBLE,
            required_value=required,
            allocated_value=Money.zero(base),
            lines=(),
            total_cost=Money.zero(base),
            baseline_cost=Money.zero(base),
            baseline_lines=(),
            shadow_prices=(),
            excluded=tuple(excluded),
            message=(
                f"No allocation satisfies every constraint. Eligible inventory offers "
                f"{Money(quantize_money(headroom), base)} of post-haircut value against a "
                f"requirement of {required}. Relaxing a concentration limit or adding "
                f"eligible inventory would restore feasibility."
            ),
        )

    headline_ranks, effective_ranks = _rankings(candidates)

    # Shadow prices. HiGHS reports marginals <= 0 for <= rows in a minimisation,
    # so the sign is flipped to read as "cost of this constraint".
    shadow: list[ConstraintShadowPrice] = []
    marginals = getattr(solution.ineqlin, "marginals", None)
    if marginals is not None:
        for (name, description), marginal in zip(labels, marginals, strict=True):
            price = -float(marginal)
            shadow.append(
                ConstraintShadowPrice(
                    name=name,
                    description=description,
                    shadow_price_bps=quantize_money(Decimal(repr(price * 10_000))),
                    binding=abs(price) > _BINDING_TOLERANCE,
                )
            )

    posted_by_candidate = [quantize_money(Decimal(repr(float(raw)))) for raw in solution.x]
    used = [
        candidate
        for candidate, posted in zip(candidates, posted_by_candidate, strict=True)
        if posted > Decimal("0.01")
    ]
    marginal_cost = max(c.cost_per_effective_unit for c in used) if used else None
    binding = _binding_scopes(shadow)

    lines: list[AllocationLine] = []
    considered: list[AllocationLine] = []
    total_cost = Decimal(0)
    allocated = Decimal(0)

    for candidate, posted in zip(candidates, posted_by_candidate, strict=True):
        selected = posted > Decimal("0.01")
        line = _line_from(
            candidate,
            posted if selected else Decimal(0),
            base,
            snapshot,
            headline_rank=headline_ranks[candidate.asset.asset_id],
            effective_rank=effective_ranks[candidate.asset.asset_id],
            selected=selected,
            not_selected_reason=(
                "" if selected else _not_selected_reason(candidate, binding, marginal_cost)
            ),
        )
        considered.append(line)
        if selected:
            lines.append(line)
            total_cost += posted * candidate.cost_rate
            allocated += posted * candidate.effective_percentage

    lines.sort(key=lambda line: line.cost_per_effective_unit_bps)
    considered.sort(key=lambda line: (not line.selected, line.cost_per_effective_unit_bps))

    baseline_lines, baseline_cost, baseline_covers = cash_first_baseline(
        candidates, required.amount, base, snapshot
    )

    return OptimizationResult(
        agreement_id=terms.agreement_id,
        snapshot_id=snapshot.snapshot_id,
        base_currency=base,
        status=OptimizerStatus.OPTIMAL,
        required_value=required,
        allocated_value=Money(quantize_money(allocated), base),
        lines=tuple(lines),
        total_cost=Money(quantize_money(total_cost), base),
        baseline_cost=Money(baseline_cost, base),
        baseline_lines=tuple(baseline_lines),
        shadow_prices=tuple(shadow),
        excluded=tuple(excluded),
        message=f"Optimal allocation across {len(lines)} assets.",
        considered=tuple(considered),
        baseline_covers=baseline_covers,
    )
