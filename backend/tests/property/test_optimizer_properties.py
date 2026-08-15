"""Optimizer invariants.

The most valuable test in the suite lives here:
:meth:`TestOptimalityInvariants.test_optimizer_never_loses_to_the_baseline`. The
product's central claim is that optimisation beats the desk heuristic. If the LP ever
costs more than cash-first, either the objective or the baseline is wrong, and the
claim is false. No amount of demo polish survives that.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aether.core.csa_terms import AssetClass, ConcentrationScope, IssuerType
from aether.core.money import Currency, Money
from aether.core.optimize import OptimizerStatus, optimize_collateral
from aether.fixtures.loader import load_agreement, load_inventory, load_snapshot

pytestmark = pytest.mark.property

USD = Currency.USD
TERMS = load_agreement()
INVENTORY = load_inventory()
SNAPSHOT = load_snapshot("MKT-2026-08-17-STRESS")

# Requirements from trivial up to roughly the eligible headroom.
requirements = st.decimals(
    min_value=Decimal("100000"),
    max_value=Decimal("18000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

SOLVER = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def solve(amount: Decimal):
    return optimize_collateral(TERMS, INVENTORY, SNAPSHOT, Money(amount, USD))


class TestFeasibilityInvariants:
    @SOLVER
    @given(requirements)
    def test_a_solved_allocation_always_covers_the_requirement(self, amount: Decimal):
        result = solve(amount)
        if result.status is not OptimizerStatus.OPTIMAL:
            return
        # One cent of tolerance for the quantisation of each line.
        tolerance = Decimal(len(result.lines)) / 100
        assert result.allocated_value.amount >= amount - tolerance

    @SOLVER
    @given(requirements)
    def test_no_asset_is_over_allocated(self, amount: Decimal):
        result = solve(amount)
        if result.status is not OptimizerStatus.OPTIMAL:
            return
        for line in result.lines:
            asset = INVENTORY.by_id(line.asset_id)
            assert line.market_value_posted.amount <= asset.available_market_value + Decimal(1)

    @SOLVER
    @given(requirements)
    def test_no_allocation_is_ever_negative(self, amount: Decimal):
        result = solve(amount)
        for line in result.lines:
            assert not line.market_value_posted.is_negative
            assert not line.effective_value.is_negative


class TestEligibilityInvariants:
    @SOLVER
    @given(requirements)
    def test_the_counterparty_own_paper_is_never_posted(self, amount: Decimal):
        """Wrong-way risk. CSA Paragraph 11(g)(iv). Non-negotiable."""
        result = solve(amount)
        assert all(line.asset_id != "US0000C2Y09" for line in result.lines)
        assert all(line.issuer != "MERIDIAN_GLOBAL" for line in result.lines)

    @SOLVER
    @given(requirements)
    def test_every_posted_asset_is_eligible(self, amount: Decimal):
        from aether.core.haircut import assess_eligibility

        result = solve(amount)
        for line in result.lines:
            assessment = assess_eligibility(INVENTORY.by_id(line.asset_id), TERMS)
            assert assessment.eligible


class TestConcentrationInvariants:
    @SOLVER
    @given(requirements)
    def test_class_caps_hold_in_every_allocation(self, amount: Decimal):
        result = solve(amount)
        if result.status is not OptimizerStatus.OPTIMAL or not result.lines:
            return

        total = sum((line.effective_value.amount for line in result.lines), Decimal(0))
        if total <= 0:
            return

        for scope, asset_class in (
            (ConcentrationScope.CORPORATE_BOND, AssetClass.CORPORATE_BOND),
            (ConcentrationScope.EQUITY, AssetClass.EQUITY),
        ):
            limit = TERMS.concentration_limit(scope)
            if limit is None:
                continue
            in_scope = sum(
                (
                    line.effective_value.amount
                    for line in result.lines
                    if line.asset_class is asset_class
                ),
                Decimal(0),
            )
            # Small tolerance for per-line quantisation.
            assert in_scope <= limit * total + Decimal("1")

    @SOLVER
    @given(requirements)
    def test_single_issuer_cap_holds_for_non_sovereigns(self, amount: Decimal):
        result = solve(amount)
        if result.status is not OptimizerStatus.OPTIMAL or not result.lines:
            return

        limit = TERMS.concentration_limit(ConcentrationScope.SINGLE_NON_SOVEREIGN_ISSUER)
        assert limit is not None

        total = sum((line.effective_value.amount for line in result.lines), Decimal(0))
        if total <= 0:
            return

        by_issuer: dict[str, Decimal] = {}
        for line in result.lines:
            asset = INVENTORY.by_id(line.asset_id)
            if asset.issuer_type is IssuerType.SOVEREIGN:
                continue
            by_issuer[asset.issuer] = (
                by_issuer.get(asset.issuer, Decimal(0)) + line.effective_value.amount
            )

        for issuer, value in by_issuer.items():
            assert value <= limit * total + Decimal("1"), f"{issuer} breaches its cap"


class TestOptimalityInvariants:
    """The product's central claim, asserted over generated inputs."""

    @SOLVER
    @given(requirements)
    def test_optimizer_never_loses_to_the_baseline(self, amount: Decimal):
        """If this fails, the objective or the baseline is wrong. Nothing else matters."""
        result = solve(amount)
        if result.status is not OptimizerStatus.OPTIMAL:
            return
        if not result.baseline_lines:
            return
        assert result.total_cost <= result.baseline_cost

    @SOLVER
    @given(requirements)
    def test_saving_is_never_negative(self, amount: Decimal):
        result = solve(amount)
        if result.status is OptimizerStatus.OPTIMAL and result.baseline_lines:
            assert not result.saving.is_negative

    @SOLVER
    @given(requirements)
    def test_cost_rises_monotonically_with_the_requirement(self, amount: Decimal):
        """Asking for more collateral can never get cheaper."""
        small = solve(amount)
        large = solve(amount + Decimal("250000"))
        if OptimizerStatus.OPTIMAL in (small.status, large.status) and (
            small.status is large.status is OptimizerStatus.OPTIMAL
        ):
            assert large.total_cost >= small.total_cost

    @SOLVER
    @given(requirements)
    def test_reported_cost_matches_the_sum_of_the_lines(self, amount: Decimal):
        result = solve(amount)
        if result.status is not OptimizerStatus.OPTIMAL:
            return
        line_total = sum((line.annual_cost.amount for line in result.lines), Decimal(0))
        assert abs(line_total - result.total_cost.amount) <= Decimal("0.10")


class TestDeterminism:
    @SOLVER
    @given(requirements)
    def test_identical_inputs_give_identical_output(self, amount: Decimal):
        first = solve(amount)
        second = solve(amount)
        assert first.total_cost == second.total_cost
        assert [line.asset_id for line in first.lines] == [line.asset_id for line in second.lines]
        assert [line.market_value_posted for line in first.lines] == [
            line.market_value_posted for line in second.lines
        ]


class TestInfeasibility:
    def test_impossible_requirement_reports_infeasible_with_a_useful_message(self):
        result = optimize_collateral(TERMS, INVENTORY, SNAPSHOT, Money.of("500000000", USD))
        assert result.status is OptimizerStatus.INFEASIBLE
        assert not result.is_feasible
        assert "post-haircut value" in result.message
        assert "concentration" in result.message

    def test_zero_requirement_allocates_nothing(self):
        result = optimize_collateral(TERMS, INVENTORY, SNAPSHOT, Money.zero(USD))
        assert result.status is OptimizerStatus.NOT_REQUIRED
        assert not result.lines
        assert result.total_cost.is_zero

    def test_no_eligible_inventory_is_infeasible_not_a_crash(self):
        """Every asset excluded by issuer. The optimizer must degrade, not explode."""
        all_issuers = frozenset(a.issuer for a in INVENTORY.assets)
        blocked = replace(TERMS, excluded_issuers=all_issuers)

        result = optimize_collateral(blocked, INVENTORY, SNAPSHOT, Money.of("1000000", USD))
        assert result.status is OptimizerStatus.INFEASIBLE
        assert "No eligible assets" in result.message
        assert len(result.excluded) == len(INVENTORY)
