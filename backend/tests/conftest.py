"""Shared test fixtures."""

from __future__ import annotations

import math
from datetime import date

import pytest

from aether.core.curves import DiscountCurve
from aether.core.market import MarketSnapshot
from aether.core.money import Currency

AS_OF = date(2026, 8, 14)


def flat_curve(currency: Currency, rate: float, as_of: date = AS_OF) -> DiscountCurve:
    """A perfectly flat continuously-compounded curve.

    Flat curves make analytic expected values computable by hand, which is what the
    golden tests need: ``DF(t) = exp(-r * t)`` exactly, at every tenor.
    """
    return DiscountCurve(
        currency=currency,
        as_of=as_of,
        pillars_years=(0.25, 1.0, 2.0, 5.0, 10.0, 30.0),
        zero_rates=(rate,) * 6,
    )


@pytest.fixture
def as_of() -> date:
    return AS_OF


@pytest.fixture
def flat_usd_5pct() -> DiscountCurve:
    return flat_curve(Currency.USD, 0.05)


@pytest.fixture
def flat_snapshot() -> MarketSnapshot:
    """Flat curves in all three currencies, with round FX rates.

    Deliberately simple so expected values in the golden tests can be written out
    analytically rather than lifted from a previous run.
    """
    from decimal import Decimal

    return MarketSnapshot(
        snapshot_id="TEST-FLAT",
        as_of=AS_OF,
        label="Flat test snapshot",
        curves={
            Currency.USD: flat_curve(Currency.USD, 0.05),
            Currency.EUR: flat_curve(Currency.EUR, 0.03),
            Currency.INR: flat_curve(Currency.INR, 0.07),
        },
        fx_spot={
            "EURUSD": Decimal("1.1000"),
            "USDINR": Decimal("88.0000"),
        },
    )


@pytest.fixture
def real_snapshots() -> dict[str, MarketSnapshot]:
    from aether.fixtures.loader import load_snapshots

    return load_snapshots()


@pytest.fixture
def base_snapshot() -> MarketSnapshot:
    from aether.fixtures.loader import load_snapshot

    return load_snapshot("MKT-2026-08-14-BASE")


@pytest.fixture
def stress_snapshot() -> MarketSnapshot:
    from aether.fixtures.loader import load_snapshot

    return load_snapshot("MKT-2026-08-17-STRESS")


@pytest.fixture
def portfolio():
    from aether.fixtures.loader import load_portfolio

    return load_portfolio()


def approx_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)
