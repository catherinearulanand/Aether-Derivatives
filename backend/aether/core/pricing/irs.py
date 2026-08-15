"""Interest rate swap valuation — quantitative function F2.

Single-curve, fixed-for-floating, ACT/365F.

.. rubric:: The maths

For each remaining period *i* with accrual ``tau_i`` and payment at ``t_i``:

    PV_fixed = sum over i of  N * K * tau_i * DF(t_i)

The floating leg uses the standard telescoping identity. Since the projected
forward is ``F_i = (DF(t_{i-1}) / DF(t_i) - 1) / tau_i``, each floating coupon's
present value is::

    N * F_i * tau_i * DF(t_i) = N * (DF(t_{i-1}) - DF(t_i))

which sums to ``N * (DF(t_0) - DF(t_n))`` across contiguous periods. The floating
leg is therefore worth the notional discounted from the first accrual start less
the notional discounted from final maturity — exact under the single-curve
assumption, and it needs no forward rates computed at all.

.. rubric:: Documented simplifications

- **Single curve.** The projection curve is the discount curve. No OIS/IBOR basis.
- **Current period.** For a swap already accruing at the valuation date, the current
  period's start is clamped to the valuation date, which values the in-flight
  floating coupon at its forward rate rather than at its already-fixed rate. The
  effect is small at the notionals here and the alternative would require a fixing
  history the prototype does not model.
- **No calendars.** Payment dates roll on the unadjusted schedule; there is no
  business-day adjustment and no holiday calendar.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from aether.core.curves import DiscountCurve, year_fraction
from aether.core.instruments import InterestRateSwap, SwapDirection
from aether.core.money import Money, quantize_money

__all__ = ["SwapLegs", "payment_schedule", "price_swap"]


@dataclass(frozen=True, slots=True)
class SwapLegs:
    """Leg-level breakdown, so the UI can show why a swap is worth what it is."""

    fixed_leg_pv: Money
    floating_leg_pv: Money
    present_value: Money
    remaining_periods: int


def _add_months(anchor: date, months: int) -> date:
    """Advance a date by whole months, clamping to the end of a short month."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1

    day = anchor.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            # 31 January + 1 month has no 31st; step back to the last valid day.
            day -= 1


def payment_schedule(swap: InterestRateSwap) -> tuple[date, ...]:
    """Unadjusted period end dates from the effective date to maturity.

    The final period is truncated at maturity if the frequency does not divide the
    tenor evenly, so the schedule always ends exactly on the maturity date.
    """
    dates: list[date] = []
    step = 1
    current = _add_months(swap.effective_date, swap.payment_frequency_months)
    while current < swap.maturity_date:
        dates.append(current)
        step += 1
        current = _add_months(swap.effective_date, swap.payment_frequency_months * step)
    dates.append(swap.maturity_date)
    return tuple(dates)


def price_swap(
    swap: InterestRateSwap,
    curve: DiscountCurve,
    as_of: date,
) -> SwapLegs:
    """Present value of ``swap`` on ``as_of`` under ``curve``.

    The result is expressed in the swap's own currency. Conversion to a reporting
    currency happens in :mod:`aether.core.exposure`, against a pinned snapshot.
    """
    if curve.currency is not swap.currency:
        raise ValueError(
            f"{swap.trade_id} is denominated in {swap.currency} but was priced "
            f"against a {curve.currency} curve."
        )
    if curve.as_of != as_of:
        raise ValueError(
            f"Curve as_of {curve.as_of} does not match valuation date {as_of}. "
            "Every calculation takes an explicit as_of and a pinned snapshot."
        )

    if as_of >= swap.maturity_date:
        zero = Money.zero(swap.currency)
        return SwapLegs(zero, zero, zero, remaining_periods=0)

    schedule = payment_schedule(swap)
    notional = float(swap.notional)
    fixed_rate = float(swap.fixed_rate)

    fixed_pv = 0.0
    remaining = 0

    # Accrual start of the first period that is still live.
    first_live_start: date | None = None
    period_start = swap.effective_date

    for period_end in schedule:
        if period_end > as_of:
            accrual_start = max(period_start, as_of)
            if first_live_start is None:
                first_live_start = accrual_start

            tau = year_fraction(accrual_start, period_end)
            df_end = curve.discount_factor(year_fraction(as_of, period_end))
            fixed_pv += notional * fixed_rate * tau * df_end
            remaining += 1

        period_start = period_end

    # Telescoped floating leg: N * (DF(first accrual start) - DF(maturity)).
    assert first_live_start is not None  # guaranteed by the maturity check above
    df_start = curve.discount_factor(year_fraction(as_of, first_live_start))
    df_maturity = curve.discount_factor(year_fraction(as_of, swap.maturity_date))
    floating_pv = notional * (df_start - df_maturity)

    fixed_leg = Money(quantize_money(Decimal(repr(fixed_pv))), swap.currency)
    floating_leg = Money(quantize_money(Decimal(repr(floating_pv))), swap.currency)

    if swap.direction is SwapDirection.RECEIVE_FIXED:
        present_value = fixed_leg - floating_leg
    else:
        present_value = floating_leg - fixed_leg

    return SwapLegs(
        fixed_leg_pv=fixed_leg,
        floating_leg_pv=floating_leg,
        present_value=present_value,
        remaining_periods=remaining,
    )


def par_rate(swap: InterestRateSwap, curve: DiscountCurve, as_of: date) -> float:
    """The fixed rate that makes this swap worth zero.

    Used by the golden tests: pricing a swap struck at its own par rate must return
    a present value of zero, which is an expected value derived from theory rather
    than from this implementation's output.
    """
    legs = price_swap(swap, curve, as_of)
    annuity_pv = float(legs.fixed_leg_pv.amount) / float(swap.fixed_rate)
    if annuity_pv == 0:
        raise ValueError(f"{swap.trade_id}: zero annuity, par rate undefined.")
    return float(legs.floating_leg_pv.amount) / annuity_pv
