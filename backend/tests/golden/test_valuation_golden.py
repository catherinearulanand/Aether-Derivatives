"""Golden reference tests for the valuation core.

Every expected value here is derived **analytically**, from the mathematics, before
the implementation is consulted. A "golden" test whose expected value was produced by
running the code proves only that the code is deterministic — it would happily
enshrine a sign error forever.

The identities used:

1. ``DF(t) = exp(-r*t)`` on a flat continuously compounded curve.
2. A swap struck at its own par rate is worth zero.
3. The floating leg telescopes to ``N * (DF(start) - DF(maturity))``.
4. An FX forward struck at the market forward rate is worth zero.
5. Covered interest parity: ``F = S * DF_buy / DF_sell``.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from itertools import pairwise

import pytest

from aether.core.curves import year_fraction
from aether.core.instruments import FXForward, InterestRateSwap, SwapDirection
from aether.core.money import Currency, Money
from aether.core.pricing.fx_forward import forward_rate, price_fx_forward
from aether.core.pricing.irs import par_rate, payment_schedule, price_swap

from ..conftest import AS_OF, flat_curve

pytestmark = pytest.mark.golden


# --------------------------------------------------------------- curves


class TestDiscountFactors:
    """Identity 1: a flat curve discounts at exp(-r*t) exactly."""

    @pytest.mark.parametrize(
        ("tenor", "expected"),
        [
            (1.0, math.exp(-0.05 * 1.0)),
            (2.0, math.exp(-0.05 * 2.0)),
            (5.0, math.exp(-0.05 * 5.0)),
            (10.0, math.exp(-0.05 * 10.0)),
        ],
    )
    def test_flat_curve_matches_closed_form(self, flat_usd_5pct, tenor, expected):
        assert flat_usd_5pct.discount_factor(tenor) == pytest.approx(expected, rel=1e-12)

    def test_discount_factor_at_zero_is_one(self, flat_usd_5pct):
        assert flat_usd_5pct.discount_factor(0.0) == 1.0
        assert flat_usd_5pct.discount_factor(-1.0) == 1.0

    def test_interpolated_tenor_matches_closed_form(self, flat_usd_5pct):
        # Between pillars, a flat curve must still give exactly exp(-r*t).
        assert flat_usd_5pct.discount_factor(3.7) == pytest.approx(math.exp(-0.05 * 3.7), rel=1e-12)

    def test_forward_rate_on_flat_curve(self, flat_usd_5pct):
        # F = (DF(1)/DF(2) - 1)/1 = exp(0.05) - 1 for a flat 5% continuous curve.
        expected = math.exp(0.05) - 1.0
        assert flat_usd_5pct.forward_rate(1.0, 2.0) == pytest.approx(expected, rel=1e-12)

    def test_log_linear_interpolation_is_linear_in_z_times_t(self):
        """Between pillars, z(t)*t interpolates linearly. Checked on a sloped curve."""
        curve = flat_curve(Currency.USD, 0.0)
        sloped = type(curve)(
            currency=Currency.USD,
            as_of=AS_OF,
            pillars_years=(1.0, 2.0),
            zero_rates=(0.02, 0.04),
        )
        # y(1) = 0.02, y(2) = 0.08. Midpoint t=1.5 => y = 0.05 => z = 0.05/1.5.
        assert sloped.zero_rate(1.5) == pytest.approx(0.05 / 1.5, rel=1e-12)
        assert sloped.discount_factor(1.5) == pytest.approx(math.exp(-0.05), rel=1e-12)


# ----------------------------------------------------------------- swaps


def make_swap(
    direction: SwapDirection = SwapDirection.RECEIVE_FIXED,
    fixed_rate: str = "0.05",
    notional: str = "100000000",
    freq: int = 6,
    effective: date = AS_OF,
    maturity: date = date(2031, 8, 14),
) -> InterestRateSwap:
    return InterestRateSwap(
        trade_id="TEST-IRS",
        netting_set_id="NS-TEST",
        notional=Decimal(notional),
        currency=Currency.USD,
        direction=direction,
        fixed_rate=Decimal(fixed_rate),
        payment_frequency_months=freq,
        effective_date=effective,
        maturity_date=maturity,
    )


class TestSwapPricing:
    def test_schedule_ends_exactly_on_maturity(self):
        schedule = payment_schedule(make_swap())
        assert schedule[-1] == date(2031, 8, 14)
        assert len(schedule) == 10  # 5 years, semi-annual

    def test_schedule_is_strictly_increasing(self):
        schedule = payment_schedule(make_swap(freq=3))
        assert all(b > a for a, b in pairwise(schedule))

    def test_floating_leg_telescopes(self, flat_usd_5pct):
        """Identity 3: floating leg = N * (DF(start) - DF(maturity))."""
        swap = make_swap()
        legs = price_swap(swap, flat_usd_5pct, AS_OF)

        t_maturity = year_fraction(AS_OF, swap.maturity_date)
        expected = float(swap.notional) * (1.0 - math.exp(-0.05 * t_maturity))

        assert float(legs.floating_leg_pv.amount) == pytest.approx(expected, rel=1e-9)

    def test_swap_at_par_rate_is_worth_zero(self, flat_usd_5pct):
        """Identity 2: a swap struck at its par rate has zero present value.

        The par rate is derived from the annuity and floating leg, independently of
        the sign convention under test, so this genuinely checks the pricer.
        """
        probe = make_swap(fixed_rate="0.05")
        par = par_rate(probe, flat_usd_5pct, AS_OF)

        at_par = make_swap(fixed_rate=str(par))
        legs = price_swap(at_par, flat_usd_5pct, AS_OF)

        # Zero to within a cent on a 100m notional.
        assert abs(float(legs.present_value.amount)) < 0.01

    def test_direction_flips_sign(self, flat_usd_5pct):
        receive = price_swap(make_swap(SwapDirection.RECEIVE_FIXED), flat_usd_5pct, AS_OF)
        pay = price_swap(make_swap(SwapDirection.PAY_FIXED), flat_usd_5pct, AS_OF)
        assert receive.present_value == -pay.present_value

    def test_receive_fixed_above_par_is_in_the_money(self, flat_usd_5pct):
        """A receiver paying below-market fixed must be worth more than one at par."""
        par = par_rate(make_swap(), flat_usd_5pct, AS_OF)

        rich = price_swap(
            make_swap(SwapDirection.RECEIVE_FIXED, fixed_rate=str(par + 0.01)),
            flat_usd_5pct,
            AS_OF,
        )
        assert rich.present_value.is_positive

    def test_rates_up_hurts_receive_fixed(self):
        """The economic assumption the whole demo scenario rests on."""
        swap = make_swap(SwapDirection.RECEIVE_FIXED)
        low = price_swap(swap, flat_curve(Currency.USD, 0.04), AS_OF)
        high = price_swap(swap, flat_curve(Currency.USD, 0.05), AS_OF)
        assert high.present_value < low.present_value

    def test_matured_swap_is_worthless(self, flat_usd_5pct):
        matured = make_swap(effective=date(2020, 1, 1), maturity=date(2025, 1, 1))
        legs = price_swap(matured, flat_usd_5pct, AS_OF)
        assert legs.present_value.is_zero
        assert legs.remaining_periods == 0

    def test_currency_mismatch_raises(self, flat_usd_5pct):
        eur_swap = InterestRateSwap(
            trade_id="X",
            netting_set_id="NS-TEST",
            notional=Decimal("1000000"),
            currency=Currency.EUR,
            direction=SwapDirection.PAY_FIXED,
            fixed_rate=Decimal("0.02"),
            payment_frequency_months=12,
            effective_date=AS_OF,
            maturity_date=date(2029, 8, 14),
        )
        with pytest.raises(ValueError, match="EUR"):
            price_swap(eur_swap, flat_usd_5pct, AS_OF)

    def test_as_of_must_match_curve(self, flat_usd_5pct):
        with pytest.raises(ValueError, match="as_of"):
            price_swap(make_swap(), flat_usd_5pct, date(2026, 8, 15))


# ---------------------------------------------------------- fx forwards


def make_forward(strike: str = "88.00", maturity: date = date(2027, 8, 14)) -> FXForward:
    return FXForward(
        trade_id="TEST-FXF",
        netting_set_id="NS-TEST",
        buy_currency=Currency.USD,
        buy_notional=Decimal("10000000"),
        sell_currency=Currency.INR,
        strike=Decimal(strike),
        maturity_date=maturity,
    )


class TestFXForward:
    def test_covered_interest_parity(self, flat_snapshot):
        """Identity 5: F = S * DF_buy / DF_sell."""
        forward = make_forward()
        t = year_fraction(AS_OF, forward.maturity_date)

        expected = 88.0 * math.exp(-0.05 * t) / math.exp(-0.07 * t)
        assert forward_rate(forward, flat_snapshot, AS_OF) == pytest.approx(expected, rel=1e-12)

    def test_forward_at_market_rate_is_worth_zero(self, flat_snapshot):
        """Identity 4: struck at the market forward, the contract has no value."""
        probe = make_forward()
        market = forward_rate(probe, flat_snapshot, AS_OF)

        at_market = make_forward(strike=f"{market:.10f}")
        valuation = price_fx_forward(at_market, flat_snapshot, AS_OF)

        assert abs(float(valuation.present_value.amount)) < 0.01

    def test_two_pricing_forms_agree(self, flat_snapshot):
        """PV = N*DF_buy*S - N*K*DF_sell  ==  N*(F - K)*DF_sell."""
        forward = make_forward(strike="85.00")
        t = year_fraction(AS_OF, forward.maturity_date)

        df_sell = math.exp(-0.07 * t)
        market = forward_rate(forward, flat_snapshot, AS_OF)
        expected = 10_000_000.0 * (market - 85.0) * df_sell

        valuation = price_fx_forward(forward, flat_snapshot, AS_OF)
        assert float(valuation.present_value.amount) == pytest.approx(expected, rel=1e-9)

    def test_cheaper_strike_is_more_valuable(self, flat_snapshot):
        cheap = price_fx_forward(make_forward(strike="80.00"), flat_snapshot, AS_OF)
        dear = price_fx_forward(make_forward(strike="95.00"), flat_snapshot, AS_OF)
        assert cheap.present_value > dear.present_value

    def test_matured_forward_is_worthless(self, flat_snapshot):
        matured = make_forward(maturity=date(2025, 1, 1))
        valuation = price_fx_forward(matured, flat_snapshot, AS_OF)
        assert valuation.present_value.is_zero


# ------------------------------------------------------------------ fx


class TestFXConversion:
    def test_direct_quote(self, flat_snapshot):
        assert flat_snapshot.fx_rate(Currency.EUR, Currency.USD) == Decimal("1.1000")

    def test_inverse_quote(self, flat_snapshot):
        rate = flat_snapshot.fx_rate(Currency.USD, Currency.EUR)
        assert rate == pytest.approx(Decimal(1) / Decimal("1.1000"))

    def test_cross_rate_via_usd(self, flat_snapshot):
        """EUR/INR is quoted nowhere and must be built as EURUSD * USDINR."""
        expected = Decimal("1.1000") * Decimal("88.0000")
        assert flat_snapshot.fx_rate(Currency.EUR, Currency.INR) == expected

    def test_identity_rate(self, flat_snapshot):
        assert flat_snapshot.fx_rate(Currency.USD, Currency.USD) == Decimal(1)

    def test_round_trip_conversion_preserves_value(self, flat_snapshot):
        original = Money.of("1000000.00", Currency.USD)
        there = flat_snapshot.convert(original, Currency.INR)
        back = flat_snapshot.convert(there, Currency.USD)
        # One cent of tolerance for the two quantizations.
        assert abs((back - original).amount) <= Decimal("0.01")
