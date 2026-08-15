"""Pinned market state.

A :class:`MarketSnapshot` is the only source of market data any calculation may see.
It is immutable and carries its own identifier, so every result can name the exact
market state it was produced from. There are no live feeds anywhere in the system —
that is a deliberate design choice in service of reproducibility, not a limitation
waiting to be removed.

FX quotes follow the fixture convention: a pair key ``"EURUSD"`` means *units of USD
per one EUR*. Rates are held as :class:`~decimal.Decimal` because they multiply
monetary amounts.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from aether.core.curves import DiscountCurve
from aether.core.money import Currency, Money, quantize_money

__all__ = ["MarketSnapshot"]

#: Pivot used to build a cross rate when no direct or inverse quote exists.
_PIVOT: Currency = Currency.USD


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """An immutable, identified set of curves and FX spots as of one date."""

    snapshot_id: str
    as_of: date
    label: str
    curves: Mapping[Currency, DiscountCurve]
    fx_spot: Mapping[str, Decimal]
    simulated: bool = True

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("MarketSnapshot requires a snapshot_id.")
        for currency, curve in self.curves.items():
            if curve.currency is not currency:
                raise ValueError(f"Curve filed under {currency} declares itself {curve.currency}.")
            if curve.as_of != self.as_of:
                raise ValueError(
                    f"{currency} curve as_of {curve.as_of} does not match snapshot "
                    f"as_of {self.as_of}. A snapshot must be internally consistent."
                )
        # Freeze the mappings so a snapshot cannot be mutated after construction.
        object.__setattr__(self, "curves", MappingProxyType(dict(self.curves)))
        object.__setattr__(self, "fx_spot", MappingProxyType(dict(self.fx_spot)))

    # ---- curves --------------------------------------------------------

    def curve(self, currency: Currency) -> DiscountCurve:
        try:
            return self.curves[currency]
        except KeyError:
            raise KeyError(
                f"Snapshot {self.snapshot_id} has no {currency} curve. "
                f"Available: {sorted(c.value for c in self.curves)}."
            ) from None

    # ---- fx ------------------------------------------------------------

    def fx_rate(self, source: Currency, target: Currency) -> Decimal:
        """Units of ``target`` per one unit of ``source``.

        Resolves a direct quote, then an inverse quote, then a cross through USD.
        Raises rather than guessing if none of those is available.
        """
        if source is target:
            return Decimal(1)

        direct = self.fx_spot.get(f"{source.value}{target.value}")
        if direct is not None:
            return direct

        inverse = self.fx_spot.get(f"{target.value}{source.value}")
        if inverse is not None:
            if inverse == 0:
                raise ValueError(f"Zero FX quote for {target.value}{source.value}.")
            return Decimal(1) / inverse

        if source is not _PIVOT and target is not _PIVOT:
            return self.fx_rate(source, _PIVOT) * self.fx_rate(_PIVOT, target)

        raise KeyError(
            f"Snapshot {self.snapshot_id} cannot resolve {source.value}/{target.value}. "
            f"Quotes available: {sorted(self.fx_spot)}."
        )

    def convert(self, money: Money, target: Currency) -> Money:
        """Convert a monetary amount at this snapshot's spot rate."""
        if money.currency is target:
            return money
        rate = self.fx_rate(money.currency, target)
        return Money(quantize_money(money.amount * rate), target)

    # ---- perturbation, for sensitivity only -----------------------------

    def with_curve(self, curve: DiscountCurve) -> MarketSnapshot:
        """A copy with one currency's curve replaced.

        Used to build bumped states for sensitivity calculation. The snapshot id
        gains a suffix so a perturbed state can never be mistaken for the pinned one
        in a result or an audit record.
        """
        curves = dict(self.curves)
        curves[curve.currency] = curve
        return MarketSnapshot(
            snapshot_id=f"{self.snapshot_id}~bump",
            as_of=self.as_of,
            label=f"{self.label} (perturbed)",
            curves=curves,
            fx_spot=dict(self.fx_spot),
            simulated=self.simulated,
        )

    def with_fx_bump(self, currency: Currency, relative: float) -> MarketSnapshot:
        """A copy in which one currency appreciates by ``relative`` against all others.

        Every quote naming ``currency`` is rescaled so the currency's *value* moves
        consistently whichever way the pair happens to be quoted: quotes of the form
        ``XXXYYY`` are units of YYY per XXX, so an appreciating base leg multiplies
        and an appreciating quote leg divides.
        """
        factor = Decimal(str(1.0 + relative))
        code = currency.value
        spots: dict[str, Decimal] = {}
        for pair, rate in self.fx_spot.items():
            if pair.startswith(code):
                spots[pair] = rate * factor
            elif pair.endswith(code):
                spots[pair] = rate / factor
            else:
                spots[pair] = rate
        return MarketSnapshot(
            snapshot_id=f"{self.snapshot_id}~fx",
            as_of=self.as_of,
            label=f"{self.label} (perturbed)",
            curves=dict(self.curves),
            fx_spot=spots,
            simulated=self.simulated,
        )

    def __str__(self) -> str:
        return f"{self.snapshot_id} ({self.label}, as of {self.as_of.isoformat()})"
