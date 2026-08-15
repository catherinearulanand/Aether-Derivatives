"""Golden reference cases for the risk-weighted sensitivity engine.

Expected values are derived independently of the implementation:

- **Bucket additivity.** The sum of the per-pillar sensitivities must reconcile to a
  single parallel one-basis-point shift of the same curve. Those are two different
  calculations — eleven one-pillar bumps against one whole-curve bump — and they must
  agree, because a parallel shift *is* the sum of the pillar shifts. They agree to
  second order rather than exactly, since ``DF(t) = exp(-z t)`` is convex in ``z``.

- **Single-bucket identity.** With one sensitivity in a bucket, the correlation
  matrix is the 1x1 identity, so ``K = sqrt(WS^2) = |WS|`` exactly. No solver, no
  approximation: arithmetic that can be checked by hand.

- **Positive semi-definiteness.** A correlation matrix that is not PSD can produce a
  negative quadratic form and an imaginary margin. The tenor matrix is built as a
  convex combination of the all-ones matrix and an Ornstein-Uhlenbeck correlation on
  log tenor, both PSD, so the combination must be PSD. Verified numerically.

- **Positive homogeneity.** Doubling every notional must double the margin. Delta is
  linear in position size and the aggregation is a norm, so this is exact.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

from aether.core.exposure import compute_exposure
from aether.core.instruments import InterestRateSwap, Portfolio
from aether.core.money import Currency
from aether.core.sensitivities import (
    IR_RISK_WEIGHTS_BP,
    RiskClass,
    _tenor_correlation,
    compute_sensitivities,
    compute_sensitivity_margin,
    ir_risk_weight,
)
from aether.fixtures.loader import load_portfolio, load_snapshot

pytestmark = pytest.mark.golden

USD = Currency.USD
AS_OF = date(2026, 8, 17)
SNAPSHOT_ID = "MKT-2026-08-17-STRESS"


@pytest.fixture(scope="module")
def portfolio():
    return load_portfolio()


@pytest.fixture(scope="module")
def snapshot():
    return load_snapshot(SNAPSHOT_ID)


@pytest.fixture(scope="module")
def result(portfolio, snapshot):
    return compute_sensitivity_margin(portfolio, snapshot, AS_OF, USD)


class TestBucketedDeltaReconciles:
    def test_usd_buckets_sum_to_a_parallel_shift(self, portfolio, snapshot):
        """Eleven one-pillar bumps must reconcile to one whole-curve bump."""
        sensitivities = compute_sensitivities(portfolio, snapshot, AS_OF, USD)
        bucketed = sum(
            (
                s.value.amount
                for s in sensitivities
                if s.risk_class is RiskClass.INTEREST_RATE and s.bucket == "USD"
            ),
            Decimal(0),
        )

        base = compute_exposure(portfolio, snapshot, AS_OF, USD).exposure
        shifted_snapshot = snapshot.with_curve(snapshot.curve(USD).shifted(1.0))
        parallel = compute_exposure(portfolio, shifted_snapshot, AS_OF, USD).exposure - base

        # Second-order agreement: DF is convex in the zero rate, so summing eleven
        # separate bumps is not identical to one combined bump. 0.5% is far tighter
        # than that curvature and far looser than a coincidence.
        assert parallel.amount != 0
        relative = abs((bucketed - parallel.amount) / parallel.amount)
        assert relative < Decimal("0.005"), f"bucketed {bucketed} vs parallel {parallel.amount}"

    def test_every_curve_pillar_produces_a_sensitivity(self, portfolio, snapshot):
        sensitivities = compute_sensitivities(portfolio, snapshot, AS_OF, USD)
        usd = [
            s
            for s in sensitivities
            if s.risk_class is RiskClass.INTEREST_RATE and s.bucket == "USD"
        ]
        assert len(usd) == len(snapshot.curve(USD).pillars_years)

    def test_fx_sensitivity_exists_for_each_non_base_currency(self, result):
        buckets = {s.bucket for s in result.sensitivities if s.risk_class is RiskClass.FX}
        assert buckets == {"EUR/USD", "INR/USD"}


class TestRiskWeights:
    def test_weights_decline_with_tenor(self):
        """Short rates move more in absolute terms than long rates."""
        weights = [weight for _, weight in IR_RISK_WEIGHTS_BP]
        assert weights == sorted(weights, reverse=True)

    def test_lookup_picks_the_nearest_tenor_in_log_space(self):
        assert ir_risk_weight(2.0) == Decimal("50")
        assert ir_risk_weight(10.0) == Decimal("41")
        # 2.1y is nearer 2y than 3y on a log scale.
        assert ir_risk_weight(2.1) == Decimal("50")

    def test_weighted_value_is_the_product(self, result):
        for sensitivity in result.sensitivities:
            expected = sensitivity.value.amount * sensitivity.risk_weight
            assert abs(sensitivity.weighted_value.amount - expected) <= Decimal("0.01")


class TestCorrelations:
    def test_diagonal_is_one(self):
        for tenor in (0.25, 1.0, 5.0, 30.0):
            assert _tenor_correlation(tenor, tenor) == pytest.approx(1.0)

    def test_correlation_decays_with_tenor_distance(self):
        near = _tenor_correlation(2.0, 3.0)
        far = _tenor_correlation(2.0, 30.0)
        assert 0 < far < near < 1

    def test_tenor_matrix_is_positive_semi_definite(self):
        """A non-PSD matrix can yield a negative variance and an imaginary margin."""
        tenors = [t for t, _ in IR_RISK_WEIGHTS_BP]
        matrix = np.array([[_tenor_correlation(a, b) for b in tenors] for a in tenors])
        eigenvalues = np.linalg.eigvalsh(matrix)
        assert eigenvalues.min() > -1e-12, f"smallest eigenvalue {eigenvalues.min()}"


class TestAggregation:
    def test_single_sensitivity_bucket_equals_its_absolute_weighted_value(self):
        """One sensitivity in a bucket: K = sqrt(WS^2) = |WS|, checkable by hand."""
        snapshot = load_snapshot(SNAPSHOT_ID)
        curve = snapshot.curve(USD)
        single = replace(
            curve,
            pillars_years=(5.0,),
            zero_rates=(curve.zero_rate(5.0),),
        )
        one_pillar = snapshot.with_curve(single)

        swap = next(t for t in load_portfolio().trades if isinstance(t, InterestRateSwap))
        portfolio = Portfolio(
            portfolio_id="TEST-ONE",
            netting_set_id=swap.netting_set_id,
            book_owner="TEST",
            trades=(swap,),
        )
        result = compute_sensitivity_margin(portfolio, one_pillar, AS_OF, USD)
        bucket = next(b for b in result.buckets if b.bucket == "USD")
        assert bucket.sensitivity_count == 1
        assert bucket.margin.amount == abs(bucket.weighted_sum.amount)

    def test_margin_is_positive(self, result):
        assert result.interest_rate_margin.is_positive
        assert result.fx_margin.is_positive
        assert result.total_margin.is_positive

    def test_total_is_at_least_the_larger_component(self, result):
        """Positive correlation between risk classes cannot reduce the total."""
        largest = max(result.interest_rate_margin.amount, result.fx_margin.amount)
        assert result.total_margin.amount >= largest

    def test_total_is_at_most_the_sum(self, result):
        """Correlation below one must produce a diversification benefit."""
        total = result.interest_rate_margin.amount + result.fx_margin.amount
        assert result.total_margin.amount <= total

    def test_vega_is_zero_by_construction(self, result):
        assert result.vega_margin.is_zero
        assert "no optionality" in result.vega_note

    def test_doubling_the_book_doubles_the_margin(self, portfolio, snapshot):
        """Delta is linear in position size and the aggregation is a norm."""
        doubled = Portfolio(
            portfolio_id=portfolio.portfolio_id,
            netting_set_id=portfolio.netting_set_id,
            book_owner=portfolio.book_owner,
            trades=tuple(
                replace(t, notional=t.notional * 2)
                if isinstance(t, InterestRateSwap)
                else replace(t, buy_notional=t.buy_notional * 2)
                for t in portfolio.trades
            ),
        )
        single = compute_sensitivity_margin(portfolio, snapshot, AS_OF, USD)
        double = compute_sensitivity_margin(doubled, snapshot, AS_OF, USD)

        ratio = double.total_margin.amount / single.total_margin.amount
        assert abs(ratio - Decimal(2)) < Decimal("0.001"), f"ratio {ratio}"


class TestClaimsDiscipline:
    def test_never_describes_itself_as_simm(self, result):
        text = f"{result.method} {result.disclaimer}".lower()
        assert "not isda simm" in text
        assert "certified" in text
        # The only occurrence of "simm" is the disclaimer denying it.
        assert text.count("simm") == 1

    def test_reports_its_own_weights_as_uncertified(self, result):
        assert "uncertified" in result.method.lower()


class TestSanity:
    def test_bump_size_is_small_enough_for_local_linearity(self, portfolio, snapshot):
        """A 1bp bump and a 2bp bump halved must agree closely."""
        base = compute_exposure(portfolio, snapshot, AS_OF, USD).exposure.amount
        curve = snapshot.curve(USD)

        one = (
            compute_exposure(
                portfolio, snapshot.with_curve(curve.bumped(5, 1.0)), AS_OF, USD
            ).exposure.amount
            - base
        )
        two = (
            compute_exposure(
                portfolio, snapshot.with_curve(curve.bumped(5, 2.0)), AS_OF, USD
            ).exposure.amount
            - base
        )
        assert one != 0
        assert abs(float(two / one) - 2.0) < 0.001

    def test_an_empty_book_is_refused_rather_than_valued(self):
        """There is no such thing as the margin on nothing.

        A portfolio with no trades is a construction error, not a zero-risk book, and
        it is rejected where it is built rather than silently producing a zero that
        would look like a valid answer.
        """
        with pytest.raises(ValueError, match="contains no trades"):
            Portfolio(
                portfolio_id="EMPTY",
                netting_set_id="NS-MERIDIAN-001",
                book_owner="TEST",
                trades=(),
            )

    def test_the_margin_is_a_real_number(self, result):
        assert not math.isnan(float(result.total_margin.amount))
        assert math.isfinite(float(result.total_margin.amount))
