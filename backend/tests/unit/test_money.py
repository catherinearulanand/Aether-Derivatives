"""Money semantics and CSA rounding.

The rounding tests matter more than they look. A CSA rounding provision moves real
cash, and "round up" in a collateral agreement means *away from zero, in the
Transferee's favour* — not *toward positive infinity*. Getting that wrong on a return
amount hands the counterparty money.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aether.core.money import (
    Currency,
    Money,
    RoundingDirection,
    quantize_money,
    round_to_increment,
)

USD = Currency.USD
EUR = Currency.EUR


class TestMoneyConstruction:
    def test_rejects_float(self):
        with pytest.raises(TypeError, match="float"):
            Money.of(1.5, USD)  # type: ignore[arg-type]

    def test_rejects_float_amount_directly(self):
        with pytest.raises(TypeError, match="Decimal"):
            Money(1.5, USD)  # type: ignore[arg-type]

    def test_rejects_nan(self):
        with pytest.raises(ValueError, match="finite"):
            Money(Decimal("NaN"), USD)

    def test_rejects_infinity(self):
        with pytest.raises(ValueError, match="finite"):
            Money(Decimal("Infinity"), USD)

    def test_normalises_scale(self):
        assert Money.of("1.5", USD) == Money.of("1.50", USD)
        assert hash(Money.of("1.5", USD)) == hash(Money.of("1.50", USD))

    def test_accepts_string_and_int(self):
        assert Money.of("100", USD).amount == Decimal("100.00")
        assert Money.of(100, USD).amount == Decimal("100.00")

    def test_is_immutable(self):
        money = Money.of("10", USD)
        with pytest.raises((AttributeError, TypeError)):
            money.amount = Decimal("20")  # type: ignore[misc]


class TestMoneyArithmetic:
    def test_addition(self):
        assert Money.of("10", USD) + Money.of("5", USD) == Money.of("15", USD)

    def test_subtraction(self):
        assert Money.of("10", USD) - Money.of("15", USD) == Money.of("-5", USD)

    def test_currency_mismatch_raises_on_add(self):
        with pytest.raises(ValueError, match="Currency mismatch"):
            Money.of("10", USD) + Money.of("5", EUR)

    def test_currency_mismatch_raises_on_compare(self):
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = Money.of("10", USD) < Money.of("5", EUR)

    def test_scaling_by_decimal(self):
        assert Money.of("100", USD) * Decimal("0.98") == Money.of("98.00", USD)

    def test_scaling_by_float_raises(self):
        with pytest.raises(TypeError, match="float"):
            Money.of("100", USD) * 0.98  # type: ignore[operator]

    def test_max_with_zero_floors(self):
        assert Money.of("-50", USD).max_with_zero() == Money.zero(USD)
        assert Money.of("50", USD).max_with_zero() == Money.of("50", USD)

    def test_negation_and_abs(self):
        assert -Money.of("10", USD) == Money.of("-10", USD)
        assert abs(Money.of("-10", USD)) == Money.of("10", USD)

    def test_no_float_drift_over_many_additions(self):
        """The reason Decimal is mandatory: 0.1 + 0.2 must be exactly 0.30."""
        total = Money.zero(USD)
        for _ in range(10):
            total = total + Money.of("0.1", USD)
        assert total == Money.of("1.00", USD)

        assert Money.of("0.1", USD) + Money.of("0.2", USD) == Money.of("0.30", USD)
        assert 0.1 + 0.2 != 0.3  # the float this design exists to avoid


class TestFormatting:
    def test_positive_formatting(self):
        assert str(Money.of("1234567.5", USD)) == "USD 1,234,567.50"

    def test_negative_uses_market_convention_parentheses(self):
        assert str(Money.of("-1234567.5", USD)) == "(USD 1,234,567.50)"


class TestRounding:
    """CSA rounding: 'rounded up ... to the nearest integral multiple of USD 100,000'."""

    INCREMENT = Money.of("100000", USD)

    def test_delivery_rounds_up_to_increment(self):
        result = round_to_increment(Money.of("12345678", USD), self.INCREMENT, RoundingDirection.UP)
        assert result == Money.of("12400000", USD)

    def test_return_rounds_down_to_increment(self):
        result = round_to_increment(
            Money.of("12345678", USD), self.INCREMENT, RoundingDirection.DOWN
        )
        assert result == Money.of("12300000", USD)

    def test_exact_multiple_is_unchanged_in_both_directions(self):
        exact = Money.of("12300000", USD)
        assert round_to_increment(exact, self.INCREMENT, RoundingDirection.UP) == exact
        assert round_to_increment(exact, self.INCREMENT, RoundingDirection.DOWN) == exact

    def test_up_means_away_from_zero_not_toward_positive_infinity(self):
        """The subtlety worth a dedicated test."""
        result = round_to_increment(
            Money.of("-12345678", USD), self.INCREMENT, RoundingDirection.UP
        )
        assert result == Money.of("-12400000", USD)

    def test_down_means_toward_zero_for_negatives(self):
        result = round_to_increment(
            Money.of("-12345678", USD), self.INCREMENT, RoundingDirection.DOWN
        )
        assert result == Money.of("-12300000", USD)

    def test_nearest_rounds_both_ways(self):
        assert round_to_increment(
            Money.of("12340000", USD), self.INCREMENT, RoundingDirection.NEAREST
        ) == Money.of("12300000", USD)
        assert round_to_increment(
            Money.of("12360000", USD), self.INCREMENT, RoundingDirection.NEAREST
        ) == Money.of("12400000", USD)

    def test_zero_increment_means_no_rounding_elected(self):
        value = Money.of("12345678.99", USD)
        assert round_to_increment(value, Money.zero(USD), RoundingDirection.UP) == value

    def test_negative_increment_raises(self):
        with pytest.raises(ValueError, match="negative"):
            round_to_increment(Money.of("100", USD), Money.of("-1000", USD), RoundingDirection.UP)

    def test_increment_currency_must_match(self):
        with pytest.raises(ValueError, match="currency"):
            round_to_increment(Money.of("100", USD), Money.of("1000", EUR), RoundingDirection.UP)

    def test_rounding_up_never_reduces_magnitude(self):
        """Invariant that protects collateral coverage."""
        for raw in ["1", "99999", "100001", "12345678.99"]:
            value = Money.of(raw, USD)
            rounded = round_to_increment(value, self.INCREMENT, RoundingDirection.UP)
            assert abs(rounded.amount) >= abs(value.amount)


class TestQuantize:
    def test_banker_rounding_is_the_valuation_default(self):
        assert quantize_money(Decimal("2.005")) == Decimal("2.00")
        assert quantize_money(Decimal("2.015")) == Decimal("2.02")
