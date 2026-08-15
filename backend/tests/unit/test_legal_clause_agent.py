"""Legal-Clause Agent: extraction, the review gate, and the evaluation harness.

The most important test here is
:meth:`TestReviewGate.test_freezing_is_blocked_while_a_field_awaits_review`. It is the
mechanical enforcement of the product's central rule — an unreviewed model value
cannot reach the margin engine. Everything else in this file supports it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aether.agents.evaluation import evaluate_extraction, load_ground_truth
from aether.agents.legal_clause import (
    CONFIDENCE_THRESHOLD,
    ExtractionError,
    document_sha256,
    extract_terms,
    load_document,
)
from aether.agents.review import (
    ReviewRequired,
    confirm_field,
    freeze_terms,
    pending_summary,
)
from aether.agents.schema import FieldSource, ReviewReason
from aether.config import Mode, Settings
from aether.core.csa_terms import Party
from aether.core.money import Currency, Money

DOCUMENT_ID = "CSA-MERIDIAN-2026"
REVIEWER = "collateral.ops@aether.example"
RATIONALE = "Party B rated AA- (S&P) at the valuation date, above the A- trigger."


@pytest.fixture(scope="module")
def extraction():
    return extract_terms(DOCUMENT_ID, Settings(mode=Mode.REPLAY))


@pytest.fixture
def confirmed(extraction):
    return confirm_field(extraction, "threshold.party_b", REVIEWER, RATIONALE)


class TestReplayExtraction:
    def test_runs_offline_with_no_key(self, extraction):
        """The demo path. No network, no ANTHROPIC_API_KEY."""
        assert extraction.mode == Mode.REPLAY.value
        assert extraction.cache_hit

    def test_extracts_every_expected_field(self, extraction):
        assert len(extraction.fields) == 21

    def test_is_deterministic(self):
        first = extract_terms(DOCUMENT_ID, Settings(mode=Mode.REPLAY))
        second = extract_terms(DOCUMENT_ID, Settings(mode=Mode.REPLAY))
        assert first.field_map.keys() == second.field_map.keys()
        assert [f.value for f in first.fields] == [f.value for f in second.fields]
        assert first.document_sha256 == second.document_sha256

    def test_anchors_to_the_document_hash(self, extraction):
        text = load_document(DOCUMENT_ID, Settings())
        assert extraction.document_sha256 == document_sha256(text)

    def test_records_reproducibility_metadata(self, extraction):
        assert extraction.model_id
        assert extraction.prompt_version
        assert extraction.temperature == 0.0

    def test_unknown_document_raises(self):
        with pytest.raises(ExtractionError, match="No document found"):
            extract_terms("NO-SUCH-DOC", Settings(mode=Mode.REPLAY))


class TestCitations:
    def test_every_field_carries_a_citation(self, extraction):
        """A field without a citation is an assertion, not an extraction."""
        assert extraction.uncited == ()

    def test_citations_quote_the_source_document(self, extraction):
        text = load_document(DOCUMENT_ID, Settings())
        for field in extraction.fields:
            assert field.citation is not None
            assert field.citation.appears_in(text), (
                f"{field.path} cites text that does not occur in the document"
            )

    def test_citations_name_a_clause(self, extraction):
        for field in extraction.fields:
            assert field.citation is not None
            assert field.citation.section


class TestConfidencePolicy:
    def test_low_confidence_is_routed_to_review_regardless_of_the_agent(self, extraction):
        """The agent cannot opt out of the threshold."""
        for field in extraction.fields:
            if field.confidence < CONFIDENCE_THRESHOLD:
                assert field.requires_review

    def test_the_conditional_threshold_is_flagged(self, extraction):
        field = extraction.field_map["threshold.party_b"]
        assert field.requires_review
        assert field.review_reason is ReviewReason.CONDITIONAL_CLAUSE
        assert field.conditional is not None
        assert field.conditional.value_if_triggered == {"amount": "0.00", "currency": "USD"}

    def test_the_conditional_cites_its_trigger_clause(self, extraction):
        field = extraction.field_map["threshold.party_b"]
        assert field.conditional is not None
        trigger = field.conditional.trigger_citation
        assert trigger is not None
        assert trigger.section == "11(g)(ii)"

    def test_exactly_one_field_needs_review(self, extraction):
        assert len(extraction.pending_review) == 1
        assert extraction.pending_review[0].path == "threshold.party_b"

    def test_the_unconditional_party_a_threshold_is_not_flagged(self, extraction):
        assert not extraction.field_map["threshold.party_a"].requires_review


class TestReviewGate:
    """The mechanical enforcement of the core principle."""

    def test_freezing_is_blocked_while_a_field_awaits_review(self, extraction):
        with pytest.raises(ReviewRequired) as exc:
            freeze_terms(extraction, "CSA-MERIDIAN-2026", "NS-MERIDIAN-001")

        assert "threshold.party_b" in str(exc.value)
        assert "unreviewed" in str(exc.value)

    def test_freezing_succeeds_once_confirmed(self, confirmed):
        terms = freeze_terms(confirmed, "CSA-MERIDIAN-2026", "NS-MERIDIAN-001")
        assert terms.agreement_id == "CSA-MERIDIAN-2026"
        assert terms.base_currency is Currency.USD

    def test_confirmation_records_who_decided_and_why(self, confirmed):
        field = confirmed.field_map["threshold.party_b"]
        assert field.source is FieldSource.HUMAN
        assert field.reviewer == REVIEWER
        assert field.reviewer_rationale == RATIONALE
        assert field.is_resolved

    def test_the_review_flag_survives_confirmation_as_history(self, confirmed):
        """Confirming does not erase that the field needed a human."""
        assert confirmed.field_map["threshold.party_b"].requires_review

    def test_a_reviewer_may_override_the_extracted_value(self, extraction):
        """If the Ratings Event *is* in effect, the Threshold is zero."""
        overridden = confirm_field(
            extraction,
            "threshold.party_b",
            REVIEWER,
            "Ratings Event in effect: Party B downgraded to BBB+ on 2026-08-15.",
            value={"amount": "0.00", "currency": "USD"},
        )
        terms = freeze_terms(overridden, "CSA-MERIDIAN-2026", "NS-MERIDIAN-001")
        assert terms.party_b.threshold == Money.zero(Currency.USD)

    def test_a_confirmation_without_a_rationale_is_refused(self, extraction):
        with pytest.raises(ValueError, match="rationale is required"):
            confirm_field(extraction, "threshold.party_b", REVIEWER, "   ")

    def test_confirming_an_unknown_field_raises(self, extraction):
        with pytest.raises(KeyError):
            confirm_field(extraction, "not.a.field", REVIEWER, "x")

    def test_extractions_are_immutable(self, extraction, confirmed):
        """Confirming returns a new result; the original is untouched."""
        assert extraction.field_map["threshold.party_b"].source is FieldSource.AGENT
        assert confirmed.field_map["threshold.party_b"].source is FieldSource.HUMAN


class TestPendingSummary:
    def test_explains_the_decision_to_the_reviewer(self, extraction):
        items = pending_summary(extraction)
        assert len(items) == 1

        item = items[0]
        assert item.path == "threshold.party_b"
        assert item.current_value == "USD 5,000,000.00"
        assert item.alternative == "USD 0.00"
        assert "Ratings Event" in item.question
        assert "11(b)(iii)(A)" in item.citation

    def test_is_empty_once_everything_is_resolved(self, confirmed):
        assert pending_summary(confirmed) == ()


class TestFrozenTermsMatchTheDocument:
    """The extracted-then-frozen terms must equal the hand-authored agreement."""

    def test_thresholds(self, confirmed):
        terms = freeze_terms(confirmed, "CSA-MERIDIAN-2026", "NS-MERIDIAN-001")
        assert terms.terms_for(Party.PARTY_A).threshold == Money.of("10000000", Currency.USD)
        assert terms.terms_for(Party.PARTY_B).threshold == Money.of("5000000", Currency.USD)

    def test_fx_haircut_and_rounding(self, confirmed):
        terms = freeze_terms(confirmed, "CSA-MERIDIAN-2026", "NS-MERIDIAN-001")
        assert terms.fx_haircut_pct == Decimal("0.08")
        assert terms.rounding.increment == Money.of("100000", Currency.USD)
        assert terms.mta_before_rounding

    def test_eligible_collateral_schedule(self, confirmed):
        terms = freeze_terms(confirmed, "CSA-MERIDIAN-2026", "NS-MERIDIAN-001")
        assert len(terms.eligible_collateral) == 10
        assert {item.ref for item in terms.eligible_collateral} == set("ABCDEFGHIJ")

    def test_matches_the_committed_agreement_fixture(self, confirmed):
        """Extraction path and fixture path must agree, or one of them is wrong."""
        from aether.fixtures.loader import load_agreement

        extracted = freeze_terms(
            confirmed,
            "CSA-MERIDIAN-2026",
            "NS-MERIDIAN-001",
            excluded_issuers=frozenset({"MERIDIAN_GLOBAL"}),
            governing_law="English law",
        )
        committed = load_agreement()

        assert extracted.party_a == committed.party_a
        assert extracted.party_b == committed.party_b
        assert extracted.rounding == committed.rounding
        assert extracted.fx_haircut_pct == committed.fx_haircut_pct
        assert extracted.mta_before_rounding == committed.mta_before_rounding
        assert extracted.eligible_currencies == committed.eligible_currencies
        assert extracted.eligible_collateral == committed.eligible_collateral
        assert extracted.concentration_limits == committed.concentration_limits


class TestEvaluationHarness:
    def test_scores_against_ground_truth(self, extraction):
        report = evaluate_extraction(extraction)
        assert report.scored_count == 21
        assert not report.missing_fields

    def test_meets_every_target(self, extraction):
        report = evaluate_extraction(extraction)
        assert report.value_accuracy >= Decimal("0.90")
        assert report.citation_accuracy >= Decimal("0.80")
        assert report.review_flag_recall == Decimal("1.000")
        assert report.passes

    def test_catches_a_missed_review_flag(self, extraction):
        """The failure mode the harness exists to catch, injected deliberately."""
        unflagged = extraction.with_field(
            extraction.field_map["threshold.party_b"].model_copy(
                update={"requires_review": False, "confidence": 0.99}
            )
        )
        report = evaluate_extraction(unflagged)

        assert report.review_flag_recall < Decimal("1.000")
        assert not report.passes
        assert len(report.missed_review_flags) == 1
        assert "MISSED REVIEW FLAG" in report.missed_review_flags[0].note

    def test_catches_a_wrong_value(self, extraction):
        wrong = extraction.with_field(
            extraction.field_map["threshold.party_a"].model_copy(
                update={"value": {"amount": "1.00", "currency": "USD"}}
            )
        )
        report = evaluate_extraction(wrong)
        assert report.value_accuracy < Decimal("1.000")

    def test_money_compares_as_decimal_not_float(self, extraction):
        """'5000000.00' and '5000000.0' are the same amount."""
        restated = extraction.with_field(
            extraction.field_map["threshold.party_b"].model_copy(
                update={"value": {"amount": "5000000.0", "currency": "USD"}}
            )
        )
        report = evaluate_extraction(restated)
        score = next(s for s in report.scores if s.path == "threshold.party_b")
        assert score.value_match

    def test_ground_truth_declares_itself_simulated(self):
        truth = load_ground_truth(DOCUMENT_ID)
        assert truth["_provenance"]["simulated"] is True


class TestModeSelection:
    def test_live_without_a_key_falls_back_to_replay(self, monkeypatch):
        """A demo that fails over beats a demo that fails closed."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = extract_terms(DOCUMENT_ID, Settings(mode=Mode.LIVE))
        assert result.mode == Mode.REPLAY.value

    def test_replay_needs_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert extract_terms(DOCUMENT_ID, Settings(mode=Mode.REPLAY)).cache_hit
