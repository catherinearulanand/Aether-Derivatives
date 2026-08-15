"""Money, currency and rounding.

Every monetary boundary in AETHER passes through this module. Floats are permitted
inside curve interpolation and the LP solver; anything that becomes a cash amount is
a :class:`Money`.

Rounding is never left to a default. The three policies used by the system are named
explicitly here so a reader can see which convention applied to any given figure:

- ``ROUND_HALF_EVEN`` for valuation, the unbiased choice for marking positions.
- ``ROUND_UP`` for collateral delivery amounts — rounding in the Transferee's favour.
- ``ROUND_DOWN`` for collateral return amounts — likewise in the Transferee's favour.

This module is part of the deterministic core: no I/O, no network, no clock,
no framework dependency, no mutable module state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, localcontext
from enum import StrEnum
from typing import Final, Self

__all__ = [
    "CENT",
    "Currency",
    "Money",
    "RoundingDirection",
    "quantize_money",
    "round_to_increment",
]

#: Working precision. Wide enough that intermediate products never lose cents at the
#: notionals this system handles (hundreds of millions), narrow enough to stay exact.
PRECISION: Final[int] = 28

#: The quantum every monetary amount is stored at.
CENT: Final[Decimal] = Decimal("0.01")


class Currency(StrEnum):
    """Currencies this prototype supports.

    A closed set rather than a free string, so an unknown currency is a load-time
    error rather than a silently mispriced trade.
    """

    USD = "USD"
    EUR = "EUR"
    INR = "INR"


class RoundingDirection(StrEnum):
    """Direction a CSA rounding provision applies in."""

    UP = "UP"
    DOWN = "DOWN"
    NEAREST = "NEAREST"


def quantize_money(value: Decimal, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    """Quantize to two decimal places under an explicit rounding mode."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return value.quantize(CENT, rounding=rounding)


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """An exact monetary amount in a known currency.

    Immutable and hashable. Arithmetic between different currencies raises rather
    than silently converting — conversion is explicit, via a pinned market snapshot.
    """

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"Money.amount must be Decimal, got {type(self.amount).__name__}. "
                "Floats are not permitted at monetary boundaries."
            )
        if self.amount.is_nan() or self.amount.is_infinite():
            raise ValueError(f"Money.amount must be finite, got {self.amount}")
        # Normalise storage so equality and hashing behave predictably:
        # Money(1.5) and Money(1.50) must be the same value.
        object.__setattr__(self, "amount", quantize_money(self.amount))
        object.__setattr__(self, "currency", Currency(self.currency))

    # ---- constructors -------------------------------------------------

    @classmethod
    def zero(cls, currency: Currency) -> Self:
        return cls(Decimal(0), currency)

    @classmethod
    def of(cls, amount: Decimal | int | str, currency: Currency) -> Self:
        """Build from a Decimal, int or string.

        Deliberately does not accept ``float``: a float literal has already lost
        precision by the time it reaches this call.
        """
        if isinstance(amount, float):
            raise TypeError(
                "Money.of does not accept float. Pass a str or Decimal so no "
                "precision is lost before construction."
            )
        return cls(Decimal(amount), currency)

    # ---- guards -------------------------------------------------------

    def _check(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError(
                f"Currency mismatch: {self.currency} vs {other.currency}. "
                "Convert explicitly through a pinned market snapshot."
            )

    # ---- arithmetic ---------------------------------------------------

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        if isinstance(factor, float):
            raise TypeError("Cannot scale Money by float. Use Decimal.")
        return Money(self.amount * Decimal(factor), self.currency)

    __rmul__ = __mul__

    # ---- comparison ---------------------------------------------------

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.amount >= other.amount

    # ---- predicates ---------------------------------------------------

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    # ---- helpers ------------------------------------------------------

    def max_with_zero(self) -> Money:
        """``max(0, self)`` — the floor used throughout the CSA calculation."""
        return self if self.amount > 0 else Money.zero(self.currency)

    def __str__(self) -> str:
        """Format with market convention: negatives in parentheses."""
        formatted = f"{abs(self.amount):,.2f}"
        if self.amount < 0:
            return f"({self.currency} {formatted})"
        return f"{self.currency} {formatted}"

    def __repr__(self) -> str:
        return f"Money('{self.amount}', {self.currency.value})"


def round_to_increment(
    value: Money,
    increment: Money,
    direction: RoundingDirection,
) -> Money:
    """Round ``value`` to an integral multiple of ``increment``.

    This implements a CSA rounding provision — for the Meridian agreement,
    "rounded up ... to the nearest integral multiple of USD 100,000".

    Rounding always applies to the magnitude and preserves sign, so ``UP`` means
    "away from zero, in the Transferee's favour" rather than "toward positive
    infinity". A negative amount rounded ``UP`` therefore becomes more negative.

    An increment of zero means the agreement elected no rounding, and the value
    passes through unchanged.
    """
    if value.currency is not increment.currency:
        raise ValueError(
            f"Rounding increment currency {increment.currency} does not match "
            f"value currency {value.currency}."
        )
    if increment.amount < 0:
        raise ValueError(f"Rounding increment must not be negative, got {increment.amount}")
    if increment.amount == 0:
        return value

    with localcontext() as ctx:
        ctx.prec = PRECISION
        magnitude = abs(value.amount)
        units = magnitude / increment.amount

        match direction:
            case RoundingDirection.UP:
                rounded_units = units.to_integral_value(rounding=ROUND_UP)
            case RoundingDirection.DOWN:
                rounded_units = units.to_integral_value(rounding=ROUND_DOWN)
            case RoundingDirection.NEAREST:
                rounded_units = units.to_integral_value(rounding=ROUND_HALF_EVEN)

        rounded = rounded_units * increment.amount

    signed = -rounded if value.amount < 0 else rounded
    return Money(signed, value.currency)
