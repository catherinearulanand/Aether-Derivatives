"""Property-based invariants for the valuation core.

These assert things that must hold for *every* input, not just the cases someone
thought to write down. They are where the unexpected sign error gets caught.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from aether.core.instruments import InterestRateSwap, SwapDirection
from aether.core.money import Currency, Money, RoundingDirection, round_to_increment
from aether.core.pricing.irs import price_swap

from ..conftest import AS_OF, flat_curve

pytestmark = pytest.mark.property

USD = Currency.USD

money_amounts = st.decimals(
    min_value=Decimal("-1e9"),
    max_value=Decimal("1e9"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

increments = st.sampled_from(
    [Decimal("1000"), Decimal("10000"), Decimal("100000"), Decimal("500000")]
)

rates = st.floats(min_value=0.001, max_value=0.15, allow_nan=False, allow_infinity=False)


class TestMoneyProperties:
    @given(money_amounts, money_amounts)
    def test_addition_is_commutative(self, a: Decimal, b: Decimal):
        assert Money(a, USD) + Money(b, USD) == Money(b, USD) + Money(a, USD)

    @given(money_amounts)
    def test_subtracting_self_is_zero(self, a: Decimal):
        assert (Money(a, USD) - Money(a, USD)).is_zero

    @given(money_amounts)
    def test_double_negation_is_identity(self, a: Decimal):
        money = Money(a, USD)
        assert -(money.__neg__()) == money

    @given(money_amounts)
    def test_max_with_zero_is_never_negative(self, a: Decimal):
        assert not Money(a, USD).max_with_zero().is_negative


class TestRoundingProperties:
    """Invariants that protect collateral coverage."""

    @given(money_amounts, increments)
    def test_rounding_up_never_reduces_magnitude(self, value: Decimal, inc: Decimal):
        money = Money(value, USD)
        rounded = round_to_increment(money, Money(inc, USD), RoundingDirection.UP)
        assert abs(rounded.amount) >= abs(money.amount)

    @given(money_amounts, increments)
    def test_rounding_down_never_increases_magnitude(self, value: Decimal, inc: Decimal):
        money = Money(value, USD)
        rounded = round_to_increment(money, Money(inc, USD), RoundingDirection.DOWN)
        assert abs(rounded.amount) <= abs(money.amount)

    @given(money_amounts, increments)
    def test_result_is_always_a_multiple_of_the_increment(self, value: Decimal, inc: Decimal):
        rounded = round_to_increment(Money(value, USD), Money(inc, USD), RoundingDirection.UP)
        assert rounded.amount % inc == 0

    @given(money_amounts, increments)
    def test_rounding_never_changes_sign(self, value: Decimal, inc: Decimal):
        money = Money(value, USD)
        rounded = round_to_increment(money, Money(inc, USD), RoundingDirection.UP)
        if not rounded.is_zero and not money.is_zero:
            assert (rounded.amount > 0) == (money.amount > 0)

    @given(money_amounts, increments)
    def test_rounding_error_is_bounded_by_the_increment(self, value: Decimal, inc: Decimal):
        money = Money(value, USD)
        for direction in (RoundingDirection.UP, RoundingDirection.DOWN):
            rounded = round_to_increment(money, Money(inc, USD), direction)
            assert abs(rounded.amount - money.amount) < inc

    @given(money_amounts, increments)
    def test_rounding_is_idempotent(self, value: Decimal, inc: Decimal):
        increment = Money(inc, USD)
        once = round_to_increment(Money(value, USD), increment, RoundingDirection.UP)
        twice = round_to_increment(once, increment, RoundingDirection.UP)
        assert once == twice


class TestCurveProperties:
    @given(rates, st.floats(min_value=0.01, max_value=30.0))
    def test_discount_factor_is_in_zero_to_one(self, rate: float, tenor: float):
        curve = flat_curve(USD, rate)
        df = curve.discount_factor(tenor)
        assert 0.0 < df <= 1.0

    @given(rates)
    def test_discount_factor_is_monotonically_decreasing(self, rate: float):
        curve = flat_curve(USD, rate)
        tenors = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
        factors = [curve.discount_factor(t) for t in tenors]
        assert all(b < a for a, b in pairwise(factors))

    @given(rates, rates)
    def test_higher_rates_discount_harder(self, low: float, high: float):
        assume(abs(high - low) > 1e-6)
        low, high = min(low, high), max(low, high)
        assert flat_curve(USD, high).discount_factor(5.0) < flat_curve(USD, low).discount_factor(
            5.0
        )

    @given(rates, st.floats(min_value=0.1, max_value=20.0))
    def test_forward_rates_are_non_negative_on_a_positive_curve(self, rate: float, tenor: float):
        """The reason interpolation is log-linear on discount factors."""
        curve = flat_curve(USD, rate)
        assert curve.forward_rate(tenor, tenor + 0.5) > 0


class TestSwapProperties:
    @settings(max_examples=50, deadline=None)
    @given(
        rate=rates,
        fixed=st.floats(min_value=0.005, max_value=0.12),
        years=st.integers(min_value=1, max_value=25),
        notional=st.integers(min_value=1_000_000, max_value=500_000_000),
    )
    def test_pay_and_receive_are_exact_mirrors(
        self, rate: float, fixed: float, years: int, notional: int
    ):
        curve = flat_curve(USD, rate)
        maturity = AS_OF + timedelta(days=365 * years)

        def build(direction: SwapDirection) -> InterestRateSwap:
            return InterestRateSwap(
                trade_id="P",
                netting_set_id="NS",
                notional=Decimal(notional),
                currency=USD,
                direction=direction,
                fixed_rate=Decimal(repr(fixed)),
                payment_frequency_months=6,
                effective_date=AS_OF,
                maturity_date=maturity,
            )

        receive = price_swap(build(SwapDirection.RECEIVE_FIXED), curve, AS_OF)
        pay = price_swap(build(SwapDirection.PAY_FIXED), curve, AS_OF)
        assert receive.present_value == -pay.present_value

    @settings(max_examples=50, deadline=None)
    @given(
        rate=rates,
        fixed=st.floats(min_value=0.005, max_value=0.12),
        years=st.integers(min_value=1, max_value=25),
    )
    def test_receive_fixed_loses_value_when_rates_rise(self, rate: float, fixed: float, years: int):
        """Monotonicity. The economic assumption the demo scenario depends on."""
        maturity = AS_OF + timedelta(days=365 * years)
        swap = InterestRateSwap(
            trade_id="P",
            netting_set_id="NS",
            notional=Decimal("100000000"),
            currency=USD,
            direction=SwapDirection.RECEIVE_FIXED,
            fixed_rate=Decimal(repr(fixed)),
            payment_frequency_months=6,
            effective_date=AS_OF,
            maturity_date=maturity,
        )

        low = price_swap(swap, flat_curve(USD, rate), AS_OF)
        high = price_swap(swap, flat_curve(USD, rate + 0.005), AS_OF)
        assert high.present_value <= low.present_value

    @settings(max_examples=40, deadline=None)
    @given(
        rate=rates,
        fixed=st.floats(min_value=0.005, max_value=0.12),
        years=st.integers(min_value=1, max_value=20),
        scale=st.integers(min_value=2, max_value=10),
    )
    def test_value_scales_linearly_with_notional(
        self, rate: float, fixed: float, years: int, scale: int
    ):
        curve = flat_curve(USD, rate)
        maturity = AS_OF + timedelta(days=365 * years)

        def build(notional: str) -> InterestRateSwap:
            return InterestRateSwap(
                trade_id="P",
                netting_set_id="NS",
                notional=Decimal(notional),
                currency=USD,
                direction=SwapDirection.RECEIVE_FIXED,
                fixed_rate=Decimal(repr(fixed)),
                payment_frequency_months=6,
                effective_date=AS_OF,
                maturity_date=maturity,
            )

        single = price_swap(build("10000000"), curve, AS_OF).present_value
        scaled = price_swap(build(str(10_000_000 * scale)), curve, AS_OF).present_value

        # One cent of tolerance per unit scaled, for quantization.
        assert abs(scaled.amount - single.amount * scale) <= Decimal(scale) / 100
