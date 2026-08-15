"""Property-based invariants for the CSA margin engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aether.core.csa import CallDirection, compute_margin_call, credit_support_amount_only
from aether.core.csa_terms import Party
from aether.core.exposure import ExposureResult
from aether.core.money import Currency, Money
from aether.fixtures.loader import load_agreement

pytestmark = pytest.mark.property

USD = Currency.USD
AS_OF = date(2026, 8, 17)
TERMS = load_agreement()

exposures = st.decimals(
    min_value=Decimal("-500000000"),
    max_value=Decimal("500000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)
positive_money = st.decimals(
    min_value=Decimal(0), max_value=Decimal("100000000"), allow_nan=False, places=2
)


def exposure_of(amount: Decimal) -> ExposureResult:
    return ExposureResult(
        netting_set_id=TERMS.netting_set_id,
        snapshot_id="PROP",
        as_of=AS_OF,
        base_currency=USD,
        exposure=Money(amount, USD),
        trade_valuations=(),
    )


class TestCreditSupportAmountInvariants:
    @given(exposures)
    def test_never_negative(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        assert not result.credit_support_amount.is_negative

    @given(exposures)
    def test_call_amount_never_negative(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        assert not result.call_amount.is_negative

    @given(exposures, positive_money)
    def test_raising_the_threshold_never_increases_the_call(self, exposure: Decimal, bump: Decimal):
        """Monotonicity in the Threshold, in both party directions."""
        base = compute_margin_call(TERMS, exposure_of(exposure))
        party = base.transferor
        terms = TERMS

        original = terms.terms_for(party)
        raised = replace(original, threshold=original.threshold + Money(bump, USD))
        bumped_terms = (
            replace(terms, party_a=raised)
            if party is Party.PARTY_A
            else replace(terms, party_b=raised)
        )

        after = compute_margin_call(bumped_terms, exposure_of(exposure))
        assert after.credit_support_amount <= base.credit_support_amount

    @given(exposures)
    def test_formula_matches_the_standalone_implementation(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        party_terms = TERMS.terms_for(result.transferor)
        expected = credit_support_amount_only(
            abs(Money(exposure, USD)),
            party_terms.independent_amount,
            party_terms.threshold,
        )
        assert result.credit_support_amount == expected

    @given(exposures)
    def test_transferor_follows_the_sign_of_exposure(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        if exposure > 0:
            assert result.transferor is Party.PARTY_B
        else:
            assert result.transferor is Party.PARTY_A


class TestGateAndRounding:
    @given(exposures)
    def test_a_transfer_is_never_below_the_mta(self, exposure: Decimal):
        """The whole point of the MTA gate."""
        result = compute_margin_call(TERMS, exposure_of(exposure))
        if result.has_call:
            assert result.call_amount >= result.minimum_transfer_amount

    @given(exposures)
    def test_a_transfer_is_always_a_multiple_of_the_increment(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        increment = TERMS.rounding.increment.amount
        assert result.call_amount.amount % increment == 0

    @given(exposures)
    def test_delivery_rounding_never_under_covers(self, exposure: Decimal):
        """Rounding a delivery must never leave the Transferee short."""
        result = compute_margin_call(TERMS, exposure_of(exposure))
        if result.direction is CallDirection.DELIVERY:
            assert result.call_amount >= result.unrounded_amount

    @given(exposures, positive_money)
    def test_return_rounding_never_over_returns(self, exposure: Decimal, posted: Decimal):
        """Rounding a return must never hand back more than is actually excess."""
        result = compute_margin_call(TERMS, exposure_of(exposure), posted_value=Money(posted, USD))
        if result.direction is CallDirection.RETURN:
            assert result.call_amount <= result.unrounded_amount

    @given(exposures, positive_money)
    def test_return_never_exceeds_the_posted_balance(self, exposure: Decimal, posted: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure), posted_value=Money(posted, USD))
        if result.direction is CallDirection.RETURN:
            assert result.call_amount <= Money(posted, USD)


class TestPostedCollateral:
    @given(exposures, positive_money)
    def test_more_collateral_never_increases_a_delivery(self, exposure: Decimal, posted: Decimal):
        bare = compute_margin_call(TERMS, exposure_of(exposure))
        with_posted = compute_margin_call(
            TERMS, exposure_of(exposure), posted_value=Money(posted, USD)
        )
        if (
            bare.direction is CallDirection.DELIVERY
            and with_posted.direction is CallDirection.DELIVERY
        ):
            assert with_posted.call_amount <= bare.call_amount


class TestTraceIntegrity:
    @settings(max_examples=30)
    @given(exposures)
    def test_trace_is_never_empty_and_always_ends_with_the_outcome(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        assert result.trace
        assert result.trace[-1].label == "Transfer required"
        assert result.trace[-1].value == result.call_amount

    @settings(max_examples=30)
    @given(exposures)
    def test_result_always_carries_reproducibility_metadata(self, exposure: Decimal):
        result = compute_margin_call(TERMS, exposure_of(exposure))
        assert result.engine_version
        assert result.snapshot_id
        assert result.as_of == AS_OF
        assert result.agreement_id == TERMS.agreement_id
