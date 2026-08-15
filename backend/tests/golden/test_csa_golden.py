"""Golden reference cases for the CSA margin engine.

The eight cases named in the test strategy, plus the haircut cases.

One expected value here is authored by the source document itself: CSA Paragraph
11(g)(i) contains the worked example ``94% x 92% = 86.48%``. That number was written
into the fixture before this engine existed, which makes it a genuinely independent
check of the FX haircut.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from aether.core.collateral import CollateralAsset
from aether.core.csa import CallDirection, compute_margin_call, zero_threshold
from aether.core.csa_terms import AssetClass, IssuerType, Party
from aether.core.exposure import ExposureResult
from aether.core.haircut import assess_eligibility, effective_valuation_percentage
from aether.core.money import Currency, Money
from aether.fixtures.loader import load_agreement, load_inventory

pytestmark = pytest.mark.golden

USD = Currency.USD
AS_OF = date(2026, 8, 17)


@pytest.fixture
def terms():
    return load_agreement()


@pytest.fixture
def inventory():
    return load_inventory()


def exposure_of(amount: str, terms) -> ExposureResult:
    """A synthetic exposure result, so CSA cases are independent of the pricer."""
    return ExposureResult(
        netting_set_id=terms.netting_set_id,
        snapshot_id="TEST-SNAP",
        as_of=AS_OF,
        base_currency=USD,
        exposure=Money.of(amount, USD),
        trade_valuations=(),
    )


# ------------------------------------------------------ the eight cases


class TestCreditSupportAmount:
    def test_case_1_exposure_below_threshold_generates_no_call(self, terms):
        """Party A owes 8m against a 10m Threshold. Nothing is due."""
        result = compute_margin_call(terms, exposure_of("-8000000", terms))

        assert result.transferor is Party.PARTY_A
        assert result.credit_support_amount.is_zero
        assert result.direction is CallDirection.NONE
        assert not result.has_call

    def test_case_2_above_threshold_but_below_mta_is_gated(self, terms):
        """Party A owes 10.3m. CSA = 300,000, under the 500,000 MTA."""
        result = compute_margin_call(terms, exposure_of("-10300000", terms))

        assert result.credit_support_amount == Money.of("300000", USD)
        assert result.gated_by_mta
        assert result.call_amount.is_zero
        assert result.direction is CallDirection.NONE

    def test_case_3_above_both_produces_a_rounded_delivery(self, terms):
        """Party A owes 19,469,510.12 -> CSA 9,469,510.12 -> rounds up to 9.5m."""
        result = compute_margin_call(terms, exposure_of("-19469510.12", terms))

        assert result.transferor is Party.PARTY_A
        assert result.credit_support_amount == Money.of("9469510.12", USD)
        assert result.unrounded_amount == Money.of("9469510.12", USD)
        assert result.call_amount == Money.of("9500000", USD)
        assert result.direction is CallDirection.DELIVERY
        assert not result.gated_by_mta

    def test_case_4_return_amount_rounds_down(self, terms):
        """Over-collateralised: 9,469,510.12 posted against a zero requirement."""
        result = compute_margin_call(
            terms, exposure_of("-8000000", terms), posted_value=Money.of("9469510.12", USD)
        )

        assert result.direction is CallDirection.RETURN
        # Credit Support Amount is zero, so the whole balance comes back,
        # rounded DOWN to the nearest 100,000 -- in the Transferee's favour.
        assert result.call_amount == Money.of("9400000", USD)

    def test_case_5_mta_tested_before_rounding(self, terms):
        """CSA Paragraph 3(b): 480,000 is gated even though it would round to 500,000."""
        assert terms.mta_before_rounding

        result = compute_margin_call(terms, exposure_of("-10480000", terms))

        assert result.unrounded_amount == Money.of("480000", USD)
        assert result.gated_by_mta
        assert result.call_amount.is_zero

    def test_case_5b_other_convention_would_pay(self, terms):
        """The same figures under the opposite convention produce a transfer.

        This is the dispute the flag exists to represent, shown in both directions.
        """
        flipped = replace(terms, mta_before_rounding=False)
        result = compute_margin_call(flipped, exposure_of("-10480000", terms))

        assert result.rounded_amount == Money.of("500000", USD)
        assert not result.gated_by_mta
        assert result.call_amount == Money.of("500000", USD)

    def test_case_6_ratings_event_zeroes_party_b_threshold(self, terms):
        """Paragraph 11(g)(ii). Party B owes 6m; the call jumps by the Threshold."""
        normal = compute_margin_call(terms, exposure_of("6000000", terms))
        assert normal.transferor is Party.PARTY_B
        # 6m + 2m IA - 5m threshold = 3m
        assert normal.credit_support_amount == Money.of("3000000", USD)

        triggered = compute_margin_call(
            zero_threshold(terms, Party.PARTY_B), exposure_of("6000000", terms)
        )
        # 6m + 2m IA - 0 = 8m
        assert triggered.credit_support_amount == Money.of("8000000", USD)
        assert triggered.credit_support_amount - normal.credit_support_amount == Money.of(
            "5000000", USD
        )

    def test_case_7_negative_exposure_floors_at_zero(self, terms):
        """Party B in the money by a little; Party A's IA is zero and Threshold 10m."""
        result = compute_margin_call(terms, exposure_of("-100", terms))
        assert result.credit_support_amount.is_zero
        assert not result.credit_support_amount.is_negative

    def test_case_8_independent_amount_applies_to_the_transferor(self, terms):
        """Party B posts an IA of 2m; Party A posts none. Direction must pick correctly."""
        b_posts = compute_margin_call(terms, exposure_of("6000000", terms))
        a_posts = compute_margin_call(terms, exposure_of("-16000000", terms))

        assert b_posts.independent_amount == Money.of("2000000", USD)
        assert a_posts.independent_amount == Money.zero(USD)
        # A: 16m + 0 - 10m = 6m.   B: 6m + 2m - 5m = 3m.
        assert a_posts.credit_support_amount == Money.of("6000000", USD)
        assert b_posts.credit_support_amount == Money.of("3000000", USD)


class TestTransferorResolution:
    """Getting this backwards yields a plausible wrong answer, so both directions."""

    def test_positive_exposure_makes_party_b_the_transferor(self, terms):
        result = compute_margin_call(terms, exposure_of("20000000", terms))
        assert result.transferor is Party.PARTY_B
        assert result.threshold == Money.of("5000000", USD)

    def test_negative_exposure_makes_party_a_the_transferor(self, terms):
        result = compute_margin_call(terms, exposure_of("-20000000", terms))
        assert result.transferor is Party.PARTY_A
        assert result.threshold == Money.of("10000000", USD)


class TestGuards:
    def test_wrong_netting_set_raises(self, terms):
        foreign = ExposureResult(
            netting_set_id="NS-SOMETHING-ELSE",
            snapshot_id="X",
            as_of=AS_OF,
            base_currency=USD,
            exposure=Money.of("-20000000", USD),
            trade_valuations=(),
        )
        with pytest.raises(ValueError, match="never net"):
            compute_margin_call(terms, foreign)

    def test_wrong_base_currency_raises(self, terms):
        wrong = ExposureResult(
            netting_set_id=terms.netting_set_id,
            snapshot_id="X",
            as_of=AS_OF,
            base_currency=Currency.EUR,
            exposure=Money.of("-20000000", Currency.EUR),
            trade_valuations=(),
        )
        with pytest.raises(ValueError, match="base currency"):
            compute_margin_call(terms, wrong)


class TestTrace:
    def test_trace_covers_every_stage(self, terms):
        result = compute_margin_call(terms, exposure_of("-19469510.12", terms))
        labels = [step.label for step in result.trace]

        for expected in [
            "Net exposure",
            "Transferor",
            "Independent Amount",
            "Threshold",
            "Credit Support Amount",
            "Minimum Transfer Amount",
            "Rounding",
            "Transfer required",
        ]:
            assert expected in labels, f"waterfall is missing '{expected}'"

    def test_every_step_cites_a_clause(self, terms):
        result = compute_margin_call(terms, exposure_of("-19469510.12", terms))
        assert all(step.clause for step in result.trace)

    def test_trace_records_which_mta_convention_applied(self, terms):
        result = compute_margin_call(terms, exposure_of("-10480000", terms))
        gate = next(s for s in result.trace if s.is_gate)
        assert "unrounded" in gate.explanation


# ---------------------------------------------------------- haircuts F8


class TestHaircuts:
    def test_documents_own_worked_example(self, terms):
        """CSA Paragraph 11(g)(i): 94% x 92% = 86.48%.

        The expected value is written in the source document, not derived here.
        """
        effective, applied = effective_valuation_percentage(Decimal("0.94"), Currency.INR, terms)
        assert applied
        assert effective == Decimal("0.8648")

    def test_base_currency_asset_takes_no_fx_haircut(self, terms):
        effective, applied = effective_valuation_percentage(Decimal("0.98"), Currency.USD, terms)
        assert not applied
        assert effective == Decimal("0.98")

    def test_eur_cash_is_haircut_for_currency_only(self, terms):
        effective, applied = effective_valuation_percentage(Decimal("1.000"), Currency.EUR, terms)
        assert applied
        assert effective == Decimal("0.92")

    @pytest.mark.parametrize(
        ("asset_id", "expected_pct"),
        [
            ("CASH-USD", Decimal("1.000")),
            ("US0000T6M01", Decimal("0.995")),
            ("US0000T3Y02", Decimal("0.980")),
            ("US0000T7Y03", Decimal("0.960")),
            ("US0000C3Y06", Decimal("0.920")),
            ("US0000E0Y08", Decimal("0.850")),
        ],
    )
    def test_usd_assets_match_the_schedule(self, terms, inventory, asset_id, expected_pct):
        result = assess_eligibility(inventory.by_id(asset_id), terms)
        assert result.eligible, result.reason
        assert result.effective_percentage == expected_pct

    def test_india_gsec_gets_the_fx_haircut(self, terms, inventory):
        result = assess_eligibility(inventory.by_id("IN0000G6Y05"), terms)
        assert result.eligible
        assert result.valuation_percentage == Decimal("0.940")
        assert result.fx_haircut_applied
        assert result.effective_percentage == Decimal("0.8648")


class TestWrongWayRisk:
    """The trap deliberately planted in the inventory fixture."""

    def test_counterparty_own_paper_is_never_eligible(self, terms, inventory):
        asset = inventory.by_id("US0000C2Y09")
        assert asset.issuer == "MERIDIAN_GLOBAL"

        result = assess_eligibility(asset, terms)
        assert not result.eligible
        assert "wrong-way" in result.reason.lower()
        assert "11(g)(iv)" in result.reason

    def test_it_would_otherwise_have_matched_a_row(self, terms, inventory):
        """Proves the exclusion is doing the work, not an accidental mismatch."""
        asset = inventory.by_id("US0000C2Y09")
        relaxed = replace(terms, excluded_issuers=frozenset())

        result = assess_eligibility(asset, relaxed)
        assert result.eligible, "asset must be otherwise eligible for the trap to be real"
        assert result.matched_item is not None
        assert result.matched_item.ref == "H"

    def test_it_is_the_cheapest_corporate_in_the_pool(self, inventory):
        """And therefore exactly what a naive optimizer would reach for first."""
        corporates = [a for a in inventory.assets if a.asset_class is AssetClass.CORPORATE_BOND]
        cheapest = min(corporates, key=lambda a: a.funding_spread_bps)
        assert cheapest.asset_id == "US0000C2Y09"


class TestEligibilityEdges:
    def test_ineligible_currency_is_rejected(self, terms):
        # A JPY asset cannot be constructed via Currency, so use an unmatched row
        # instead: an unrated corporate bond fails the AA- minimum.
        junk = CollateralAsset(
            asset_id="JUNK",
            description="Unrated corporate",
            asset_class=AssetClass.CORPORATE_BOND,
            issuer="SOME_ISSUER",
            issuer_type=IssuerType.CORPORATE,
            currency=USD,
            available_market_value=Decimal("1000000"),
            funding_spread_bps=Decimal("1"),
            remaining_maturity_years=Decimal("3"),
            rating="BBB",
        )
        result = assess_eligibility(junk, terms)
        assert not result.eligible

    def test_maturity_outside_every_band_is_rejected(self, terms):
        long_bond = CollateralAsset(
            asset_id="LONG",
            description="30y Treasury",
            asset_class=AssetClass.SOVEREIGN_BOND,
            issuer="US_TREASURY",
            issuer_type=IssuerType.SOVEREIGN,
            currency=USD,
            available_market_value=Decimal("1000000"),
            funding_spread_bps=Decimal("20"),
            remaining_maturity_years=Decimal("30"),
            rating="AA+",
        )
        result = assess_eligibility(long_bond, terms)
        assert not result.eligible
        assert "no row" in result.reason.lower()
