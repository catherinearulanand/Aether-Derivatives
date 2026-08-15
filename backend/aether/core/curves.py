"""Discount curves — quantitative function F1.

One curve per currency serves both discounting and forward projection. No OIS/IBOR
basis is modelled. That is a documented simplification, not an oversight: basis
changes no conclusion this prototype draws, and modelling it properly would require
a second curve set and a bootstrapper.

Conventions, stated rather than assumed:

- Zero rates are **continuously compounded**, so ``DF(t) = exp(-z(t) * t)``.
- Day count is **ACT/365F** throughout.
- Interpolation is **log-linear on discount factors**, which is linear interpolation
  on ``z(t) * t``. This keeps implied forward rates piecewise constant and
  non-negative between pillars, which linear-on-zero-rates does not guarantee.
- Extrapolation is **flat on the zero rate** beyond the first and last pillar.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Final

from aether.core.money import Currency

__all__ = ["DAYS_PER_YEAR", "DiscountCurve", "year_fraction"]

#: ACT/365F. Fixed denominator, so the year fraction is exact and reproducible.
DAYS_PER_YEAR: Final[float] = 365.0


def year_fraction(start: date, end: date) -> float:
    """ACT/365F year fraction. Negative when ``end`` precedes ``start``."""
    return (end - start).days / DAYS_PER_YEAR


@dataclass(frozen=True, slots=True)
class DiscountCurve:
    """A pinned zero-rate curve for one currency.

    Immutable by construction. Pillars must be strictly increasing and positive,
    so interpolation is well defined and a malformed snapshot fails at load time
    rather than producing a plausible wrong price.
    """

    currency: Currency
    as_of: date
    pillars_years: tuple[float, ...]
    zero_rates: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.pillars_years) != len(self.zero_rates):
            raise ValueError(
                f"{self.currency} curve: {len(self.pillars_years)} pillars but "
                f"{len(self.zero_rates)} rates."
            )
        if not self.pillars_years:
            raise ValueError(f"{self.currency} curve has no pillars.")
        if any(t <= 0 for t in self.pillars_years):
            raise ValueError(f"{self.currency} curve: pillar tenors must be positive.")
        if any(later <= earlier for earlier, later in pairwise(self.pillars_years)):
            raise ValueError(f"{self.currency} curve: pillars must be strictly increasing.")

    # ---- core interpolation -------------------------------------------

    def zero_rate(self, t: float) -> float:
        """Continuously compounded zero rate for tenor ``t`` in years."""
        if t <= 0:
            return self.zero_rates[0]

        pillars = self.pillars_years
        rates = self.zero_rates

        if t <= pillars[0]:
            return rates[0]
        if t >= pillars[-1]:
            return rates[-1]

        i = bisect_left(pillars, t)
        t0, t1 = pillars[i - 1], pillars[i]
        z0, z1 = rates[i - 1], rates[i]

        # Log-linear on discount factors == linear on z*t.
        y0, y1 = z0 * t0, z1 * t1
        y = y0 + (y1 - y0) * (t - t0) / (t1 - t0)
        return y / t

    def discount_factor(self, t: float) -> float:
        """``DF(t) = exp(-z(t) * t)``. Tenors at or before the as-of date discount at 1.0."""
        if t <= 0:
            return 1.0
        return math.exp(-self.zero_rate(t) * t)

    def discount_factor_at(self, target: date) -> float:
        """Discount factor to a calendar date, measured from the curve's as-of date."""
        return self.discount_factor(year_fraction(self.as_of, target))

    def forward_rate(self, t_start: float, t_end: float) -> float:
        """Simply-compounded forward rate between two tenors.

        ``F = (DF(t_start) / DF(t_end) - 1) / tau`` — the rate that makes a float
        coupon over the period worth its discounted value today.
        """
        if t_end <= t_start:
            raise ValueError(f"forward_rate requires t_end > t_start, got {t_start} -> {t_end}")
        tau = t_end - t_start
        return (self.discount_factor(t_start) / self.discount_factor(t_end) - 1.0) / tau

    def shifted(self, shift_bp: float) -> DiscountCurve:
        """Return a parallel-shifted copy. Used for sensitivity, never for pricing a trade."""
        delta = shift_bp / 10_000.0
        return DiscountCurve(
            currency=self.currency,
            as_of=self.as_of,
            pillars_years=self.pillars_years,
            zero_rates=tuple(z + delta for z in self.zero_rates),
        )

    def bumped(self, pillar_index: int, shift_bp: float) -> DiscountCurve:
        """Return a copy with a single pillar shifted.

        This is what makes a *bucketed* sensitivity possible rather than a single
        parallel PV01. Because interpolation is linear on ``z*t`` between pillars, a
        one-pillar bump perturbs only the two adjacent segments, so the resulting
        sensitivities partition the curve rather than overlapping.
        """
        if not 0 <= pillar_index < len(self.pillars_years):
            raise IndexError(
                f"{self.currency} curve has {len(self.pillars_years)} pillars; "
                f"no pillar at index {pillar_index}."
            )
        delta = shift_bp / 10_000.0
        rates = list(self.zero_rates)
        rates[pillar_index] += delta
        return DiscountCurve(
            currency=self.currency,
            as_of=self.as_of,
            pillars_years=self.pillars_years,
            zero_rates=tuple(rates),
        )
