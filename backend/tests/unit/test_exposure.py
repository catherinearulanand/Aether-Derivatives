"""Netting-set exposure, including the rule that trades under different Masters never net."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aether.core.exposure import compute_exposure
from aether.core.instruments import InterestRateSwap, Portfolio, SwapDirection
from aether.core.money import Currency

from ..conftest import AS_OF

STRESS_AS_OF = date(2026, 8, 17)


def swap(trade_id: str, netting_set: str, direction=SwapDirection.RECEIVE_FIXED):
    return InterestRateSwap(
        trade_id=trade_id,
        netting_set_id=netting_set,
        notional=Decimal("100000000"),
        currency=Currency.USD,
        direction=direction,
        fixed_rate=Decimal("0.05"),
        payment_frequency_months=6,
        effective_date=AS_OF,
        maturity_date=date(2031, 8, 14),
    )


class TestNettingSetIsolation:
    """The correctness property, enforced structurally rather than by convention."""

    def test_portfolio_rejects_foreign_netting_set(self):
        with pytest.raises(ValueError, match="never be netted"):
            Portfolio(
                portfolio_id="PF-MIXED",
                netting_set_id="NS-A",
                trades=(swap("T1", "NS-A"), swap("T2", "NS-B")),
            )

    def test_portfolio_rejects_duplicate_trade_ids(self):
        with pytest.raises(ValueError, match="duplicate"):
            Portfolio(
                portfolio_id="PF-DUP",
                netting_set_id="NS-A",
                trades=(swap("T1", "NS-A"), swap("T1", "NS-A")),
            )

    def test_portfolio_rejects_empty(self):
        with pytest.raises(ValueError, match="no trades"):
            Portfolio(portfolio_id="PF-EMPTY", netting_set_id="NS-A", trades=())

    def test_exposure_rejects_wrong_agreement_netting_set(self, flat_snapshot):
        portfolio = Portfolio(
            portfolio_id="PF-A", netting_set_id="NS-A", trades=(swap("T1", "NS-A"),)
        )
        with pytest.raises(ValueError, match="never net"):
            compute_exposure(
                portfolio, flat_snapshot, AS_OF, Currency.USD, netting_set_id="NS-OTHER"
            )

    def test_exposure_accepts_matching_netting_set(self, flat_snapshot):
        portfolio = Portfolio(
            portfolio_id="PF-A", netting_set_id="NS-A", trades=(swap("T1", "NS-A"),)
        )
        result = compute_exposure(
            portfolio, flat_snapshot, AS_OF, Currency.USD, netting_set_id="NS-A"
        )
        assert result.netting_set_id == "NS-A"


class TestNetting:
    def test_offsetting_trades_net_to_zero(self, flat_snapshot):
        portfolio = Portfolio(
            portfolio_id="PF-FLAT",
            netting_set_id="NS-A",
            trades=(
                swap("T1", "NS-A", SwapDirection.RECEIVE_FIXED),
                swap("T2", "NS-A", SwapDirection.PAY_FIXED),
            ),
        )
        result = compute_exposure(portfolio, flat_snapshot, AS_OF, Currency.USD)
        assert result.exposure.is_zero

    def test_netting_benefit_is_reported(self, flat_snapshot):
        portfolio = Portfolio(
            portfolio_id="PF-FLAT",
            netting_set_id="NS-A",
            trades=(
                swap("T1", "NS-A", SwapDirection.RECEIVE_FIXED),
                swap("T2", "NS-A", SwapDirection.PAY_FIXED),
            ),
        )
        result = compute_exposure(portfolio, flat_snapshot, AS_OF, Currency.USD)
        # One leg is in the money, the other equally out. Netting removes all of it.
        assert result.gross_positive.is_positive
        assert result.netting_benefit == result.gross_positive


class TestSnapshotPinning:
    def test_as_of_must_match_snapshot(self, flat_snapshot):
        portfolio = Portfolio(
            portfolio_id="PF-A", netting_set_id="NS-A", trades=(swap("T1", "NS-A"),)
        )
        with pytest.raises(ValueError, match="Pin the snapshot"):
            compute_exposure(portfolio, flat_snapshot, date(2026, 9, 1), Currency.USD)

    def test_result_carries_provenance(self, flat_snapshot):
        portfolio = Portfolio(
            portfolio_id="PF-A", netting_set_id="NS-A", trades=(swap("T1", "NS-A"),)
        )
        result = compute_exposure(portfolio, flat_snapshot, AS_OF, Currency.USD)
        assert result.snapshot_id == "TEST-FLAT"
        assert result.as_of == AS_OF
        assert result.base_currency is Currency.USD


class TestAgainstRealFixtures:
    """The demo scenario's economics, asserted rather than assumed."""

    def test_loads_and_prices_the_whole_book(self, portfolio, base_snapshot):
        result = compute_exposure(
            portfolio, base_snapshot, AS_OF, Currency.USD, netting_set_id="NS-MERIDIAN-001"
        )
        assert result.trade_count == 8
        assert all(v.base_value.currency is Currency.USD for v in result.trade_valuations)

    def test_rate_shock_moves_exposure_against_party_a(
        self, portfolio, base_snapshot, stress_snapshot
    ):
        """The scenario design: under stress, Party A must owe collateral.

        If this ever fails, the fixtures no longer produce a demo and the market
        scenario needs redesigning — not the engine.
        """
        base = compute_exposure(portfolio, base_snapshot, AS_OF, Currency.USD)
        stress = compute_exposure(portfolio, stress_snapshot, STRESS_AS_OF, Currency.USD)

        assert stress.exposure < base.exposure, "rate shock must reduce Party A's position"
        assert stress.exposure.is_negative, "Party A must be out of the money under stress"

    def test_stress_loss_is_material(self, portfolio, stress_snapshot):
        """The loss must exceed Party A's USD 10m Threshold, or there is no call."""
        stress = compute_exposure(portfolio, stress_snapshot, STRESS_AS_OF, Currency.USD)
        assert abs(stress.exposure.amount) > Decimal("10000000")

    def test_per_trade_breakdown_sums_to_total(self, portfolio, base_snapshot):
        result = compute_exposure(portfolio, base_snapshot, AS_OF, Currency.USD)
        total = sum((v.base_value.amount for v in result.trade_valuations), start=Decimal(0))
        assert total == result.exposure.amount
