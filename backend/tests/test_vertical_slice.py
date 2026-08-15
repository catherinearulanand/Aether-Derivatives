"""The vertical slice, end to end.

    CSA fixture
      -> Legal-Clause Agent extraction
      -> typed CSATerms with citations
      -> human confirmation
      -> frozen Agreement
      -> portfolio + pinned market snapshot
      -> deterministic exposure and margin
      -> collateral optimisation
      -> decision
      -> hash-chained audit trail

This is the demo path. If it goes red, the demo is broken — which is exactly why it
is a test rather than a slide. It runs offline in replay mode with no API key.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from aether.agents.evaluation import evaluate_extraction
from aether.agents.legal_clause import extract_terms
from aether.agents.review import ReviewRequired, confirm_field, freeze_terms
from aether.config import Mode, Settings
from aether.core.csa import CallDirection
from aether.core.decision import DecisionAction, DecisionStatus
from aether.core.money import Currency, Money
from aether.core.optimize import OptimizerStatus
from aether.fixtures.loader import load_inventory, load_portfolio, load_snapshot
from aether.pipeline import run_pipeline

STRESS_DATE = date(2026, 8, 17)
DOCUMENT_ID = "CSA-MERIDIAN-2026"
REVIEWER = "collateral.ops@aether.example"

pytestmark = pytest.mark.slice


@pytest.fixture(scope="module")
def slice_result():
    """Run the complete slice from the document, not from the agreement fixture.

    This deliberately goes through extraction and the review gate rather than
    loading pre-frozen terms, so the test exercises the real path a demo follows.
    """
    settings = Settings(mode=Mode.REPLAY)

    # 1. Extract.
    extraction = extract_terms(DOCUMENT_ID, settings)

    # 2. The gate must refuse before review.
    with pytest.raises(ReviewRequired):
        freeze_terms(extraction, DOCUMENT_ID, "NS-MERIDIAN-001")

    # 3. Reviewer confirms the conditional Threshold.
    confirmed = confirm_field(
        extraction,
        "threshold.party_b",
        REVIEWER,
        "Party B rated AA- (S&P) at the valuation date, above the A- trigger.",
    )

    # 4. Freeze into computable terms.
    terms = freeze_terms(
        confirmed,
        agreement_id=DOCUMENT_ID,
        netting_set_id="NS-MERIDIAN-001",
        excluded_issuers=frozenset({"MERIDIAN_GLOBAL"}),
        governing_law="English law",
    )

    # 5-9. Run the deterministic pipeline on those terms.
    result = run_pipeline(
        terms,
        load_portfolio(),
        load_inventory(),
        load_snapshot("MKT-2026-08-17-STRESS"),
        STRESS_DATE,
        run_id="RUN-SLICE",
    )
    return extraction, confirmed, terms, result


class TestSliceCompletes:
    def test_extraction_produces_cited_fields(self, slice_result):
        extraction, _, _, _ = slice_result
        assert len(extraction.fields) == 21
        assert extraction.uncited == ()
        assert extraction.mode == "replay"

    def test_extraction_meets_its_targets(self, slice_result):
        extraction, _, _, _ = slice_result
        report = evaluate_extraction(extraction)
        assert report.passes
        assert report.review_flag_recall == Decimal("1.000")

    def test_terms_freeze_only_after_review(self, slice_result):
        _, confirmed, terms, _ = slice_result
        assert confirmed.is_ready_to_freeze
        assert terms.agreement_id == DOCUMENT_ID
        assert terms.party_b.threshold == Money.of("5000000", Currency.USD)

    def test_margin_call_is_produced(self, slice_result):
        *_, result = slice_result
        call = result.margin_call
        assert call.direction is CallDirection.DELIVERY
        assert call.call_amount == Money.of("9500000", Currency.USD)
        assert not call.gated_by_mta

    def test_collateral_is_optimised(self, slice_result):
        *_, result = slice_result
        allocation = result.allocation
        assert allocation is not None
        assert allocation.status is OptimizerStatus.OPTIMAL
        assert allocation.total_cost < allocation.baseline_cost
        assert allocation.allocated_value >= allocation.required_value

    def test_decision_is_recorded_and_needs_approval(self, slice_result):
        *_, result = slice_result
        decision = result.decision
        assert decision.action is DecisionAction.POST_COLLATERAL
        assert decision.status is DecisionStatus.PENDING_APPROVAL
        assert decision.requires_human_approval

    def test_audit_chain_verifies(self, slice_result):
        *_, result = slice_result
        valid, break_at, _ = result.audit.verify()
        assert valid
        assert break_at is None
        assert len(result.audit) == 15


class TestSliceInvariants:
    """Properties that must hold for the demo to be honest."""

    def test_wrong_way_asset_is_never_posted(self, slice_result):
        *_, result = slice_result
        assert result.allocation is not None
        assert all(line.issuer != "MERIDIAN_GLOBAL" for line in result.allocation.lines)

    def test_extracted_terms_agree_with_the_committed_agreement(self, slice_result):
        """The document path and the fixture path must produce the same terms."""
        from aether.fixtures.loader import load_agreement

        _, _, extracted, _ = slice_result
        committed = load_agreement()

        assert extracted.party_a == committed.party_a
        assert extracted.party_b == committed.party_b
        assert extracted.eligible_collateral == committed.eligible_collateral
        assert extracted.fx_haircut_pct == committed.fx_haircut_pct

    def test_initial_margin_is_reported_separately(self, slice_result):
        *_, result = slice_result
        assert result.initial_margin.initial_margin.is_positive
        assert result.margin_call.initial_margin.is_zero

    def test_no_step_lost_precision(self, slice_result):
        """Every monetary figure is still an exact Decimal at the end of the slice."""
        *_, result = slice_result
        for value in (
            result.exposure.exposure,
            result.margin_call.credit_support_amount,
            result.margin_call.call_amount,
            result.decision.amount,
        ):
            assert isinstance(value.amount, Decimal)


class TestSliceIsReproducible:
    def test_running_the_whole_slice_twice_gives_identical_hashes(self):
        """The reproducibility claim, asserted over the full path."""
        settings = Settings(mode=Mode.REPLAY)

        def once() -> str:
            extraction = extract_terms(DOCUMENT_ID, settings)
            confirmed = confirm_field(
                extraction, "threshold.party_b", REVIEWER, "Above the trigger."
            )
            terms = freeze_terms(
                confirmed,
                agreement_id=DOCUMENT_ID,
                netting_set_id="NS-MERIDIAN-001",
                excluded_issuers=frozenset({"MERIDIAN_GLOBAL"}),
            )
            result = run_pipeline(
                terms,
                load_portfolio(),
                load_inventory(),
                load_snapshot("MKT-2026-08-17-STRESS"),
                STRESS_DATE,
                run_id="RUN-REPRO",
            )
            return result.audit.head_hash

        assert once() == once()


class TestSliceRunsOffline:
    def test_no_api_key_is_needed(self, monkeypatch):
        """The demo path must work with the network unplugged."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        extraction = extract_terms(DOCUMENT_ID, Settings(mode=Mode.REPLAY))
        assert extraction.cache_hit
        assert extraction.latency_ms == 0
