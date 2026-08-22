"""The governance controls, and the ways round them that must not work.

Each class here corresponds to a clause of the principle the architecture claims:

    AI interprets → deterministic engines calculate → optimisation proposes →
    humans authorise → cryptographic evidence proves what happened.

A control that is only asserted in a docstring is a convention. These tests are
what make each one a control.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import ClassVar

import pytest

from aether.governance.authority import (
    AUTHORITY,
    Actor,
    AuthorityError,
    Capability,
    holders_of,
    may,
    require,
)
from aether.governance.escalation import Band, EscalationPolicy, classify
from aether.governance.evidence import build_pack, content_hash
from aether.governance.integrity import Severity as IntegritySeverity
from aether.governance.integrity import preflight
from aether.governance.registry import (
    REGISTRY,
    DeploymentStatus,
    EvaluationStatus,
    ModelNotDeployedError,
    UseCase,
    attribute,
    promote,
    resolve,
)
from aether.governance.supervision import (
    ApprovalState,
    Proposal,
    SupervisionError,
    record_approval,
    state_of,
)

STAMP = "2026-08-22T10:00:00Z"


def _assessment(band: Band):
    """An assessment in a given band, built through the real classifier."""
    if band is Band.CRITICAL:
        return classify(
            transfer_amount=Decimal("0"),
            currency="USD",
            integrity_failures=("The audit chain does not verify.",),
        )
    if band is Band.HIGH:
        return classify(transfer_amount=Decimal("9500000"), currency="USD")
    if band is Band.MEDIUM:
        return classify(transfer_amount=Decimal("2000000"), currency="USD")
    return classify(transfer_amount=Decimal("100"), currency="USD")


# ============================================================== §4 authority


class TestAuthorityBoundary:
    """AI interprets. It does not calculate, authorise or execute."""

    @pytest.mark.parametrize(
        "actor",
        [Actor.LEGAL_AGENT, Actor.RISK_ENGINE, Actor.COLLATERAL_OPTIMIZER, Actor.DESK_ASSISTANT],
    )
    @pytest.mark.parametrize(
        "forbidden",
        [
            Capability.APPROVE_DECISION,
            Capability.REJECT_DECISION,
            Capability.CONFIRM_TERM,
            Capability.FREEZE_AGREEMENT,
            Capability.EXECUTE_SETTLEMENT,
        ],
    )
    def test_no_ai_actor_can_authorise_anything(self, actor, forbidden):
        """The central claim, asserted across every AI actor and every gate."""
        assert not may(actor, forbidden)
        with pytest.raises(AuthorityError):
            require(actor, forbidden)

    def test_legal_agent_cannot_reach_a_calculation(self):
        for capability in (Capability.COMPUTE_EXPOSURE, Capability.COMPUTE_MARGIN):
            assert not may(Actor.LEGAL_AGENT, capability)

    def test_risk_engine_cannot_reach_an_interpretation(self):
        for capability in (
            Capability.EXTRACT_TERMS,
            Capability.CONFIRM_TERM,
            Capability.READ_DOCUMENT,
        ):
            assert not may(Actor.RISK_ENGINE, capability)

    def test_optimiser_cannot_alter_terms_or_risk_output(self):
        for capability in (
            Capability.CONFIRM_TERM,
            Capability.FREEZE_AGREEMENT,
            Capability.COMPUTE_MARGIN,
            Capability.APPROVE_DECISION,
        ):
            assert not may(Actor.COLLATERAL_OPTIMIZER, capability)

    def test_nobody_can_execute_settlement(self):
        """AETHER has no connectivity. Granting the capability would imply it does."""
        assert holders_of(Capability.EXECUTE_SETTLEMENT) == ()
        for actor in Actor:
            assert not may(actor, Capability.EXECUTE_SETTLEMENT)

    def test_auditor_is_read_only(self):
        held = AUTHORITY[Actor.HUMAN_AUDITOR]
        mutating = {
            Capability.CONFIRM_TERM,
            Capability.FREEZE_AGREEMENT,
            Capability.APPROVE_DECISION,
            Capability.REJECT_DECISION,
            Capability.OPTIMISE_ALLOCATION,
            Capability.CONFIGURE_SYSTEM,
            Capability.PROMOTE_MODEL,
        }
        assert not (held & mutating), "An auditor who can change what they audit is not one."

    def test_unknown_actor_holds_nothing(self):
        assert not may("SUPERUSER", Capability.APPROVE_DECISION)
        assert not may("", Capability.READ_AUDIT)

    def test_unknown_capability_is_denied_not_allowed(self):
        """A typo in a capability name must fail closed."""
        assert not may(Actor.HUMAN_ADMIN, "DO_ANYTHING")
        with pytest.raises(AuthorityError):
            require(Actor.HUMAN_ADMIN, "DO_ANYTHING")

    def test_refusal_names_who_does_hold_it(self):
        with pytest.raises(AuthorityError) as excinfo:
            require(Actor.HUMAN_AUDITOR, Capability.APPROVE_DECISION)
        assert "HUMAN_APPROVER" in str(excinfo.value)

    def test_least_privilege_no_actor_holds_everything(self):
        everything = set(Capability)
        for actor, held in AUTHORITY.items():
            assert held != everything, f"{actor} holds every capability."


# ============================================================ §3/§12 registry


class TestModelRegistry:
    def test_every_ai_output_is_attributable(self):
        card = resolve(UseCase.LEGAL_CLAUSE_EXTRACTION)
        stamp = attribute(card, mode="replay")

        payload = stamp.as_payload()
        for field in ("model_id", "model_version", "prompt_version", "policy_version"):
            assert payload[field], f"{field} must be recorded on every output."

    def test_replay_is_not_attributed_as_a_live_call(self):
        """A replayed extraction was not produced by a model call in this run."""
        card = resolve(UseCase.LEGAL_CLAUSE_EXTRACTION)
        assert attribute(card, mode="replay").mode == "replay"
        assert attribute(card, mode="live").mode == "live"

    def test_undeployed_model_is_refused(self):
        """APPROVED is one step short of DEPLOYED, and one step short is refused."""
        registry = tuple(
            replace(card, deployment_status=DeploymentStatus.APPROVED) for card in REGISTRY
        )
        with pytest.raises(ModelNotDeployedError):
            resolve(UseCase.LEGAL_CLAUSE_EXTRACTION, registry)

    def test_failed_evaluation_is_refused_even_when_deployed(self):
        registry = tuple(
            replace(card, evaluation_status=EvaluationStatus.FAILED) for card in REGISTRY
        )
        with pytest.raises(ModelNotDeployedError):
            resolve(UseCase.LEGAL_CLAUSE_EXTRACTION, registry)

    def test_two_deployed_models_for_one_use_case_is_refused(self):
        """Ambiguous attribution is worse than none — it looks authoritative."""
        card = resolve(UseCase.LEGAL_CLAUSE_EXTRACTION)
        with pytest.raises(ModelNotDeployedError, match="simultaneously deployed"):
            resolve(UseCase.LEGAL_CLAUSE_EXTRACTION, (card, card))

    def test_promotion_cannot_skip_a_step(self):
        card = replace(REGISTRY[0], deployment_status=DeploymentStatus.REGISTERED)
        with pytest.raises(ValueError, match="not skipped"):
            promote(card, DeploymentStatus.DEPLOYED, "ops.admin@aether.example", STAMP)

    def test_promotion_requires_a_named_approver(self):
        card = replace(REGISTRY[0], deployment_status=DeploymentStatus.REGISTERED)
        with pytest.raises(ValueError, match="name"):
            promote(card, DeploymentStatus.EVALUATED, "   ", STAMP)

    def test_promotion_returns_a_new_card_and_records_who(self):
        card = replace(REGISTRY[0], deployment_status=DeploymentStatus.REGISTERED)
        promoted = promote(card, DeploymentStatus.EVALUATED, "ops.admin", STAMP, "eval run 7")

        assert card.deployment_status is DeploymentStatus.REGISTERED, "original mutated"
        assert promoted.deployment_status is DeploymentStatus.EVALUATED
        assert "ops.admin" in promoted.change_note
        assert promoted.updated_at == STAMP

    def test_prohibited_actions_name_their_enforcement_point(self):
        """A prohibition nobody can locate is a promise, not a control."""
        for card in REGISTRY:
            assert card.prohibited_actions
            assert any(
                "enforced" in action or "mitigated" in action for action in card.prohibited_actions
            )


# =========================================================== §7 escalation


class TestEscalation:
    def test_thresholds_are_configurable_not_compiled_in(self):
        strict = EscalationPolicy(
            medium_transfer=Decimal("1"),
            high_transfer=Decimal("2"),
            policy_version="test/v1",
        )
        assessment = classify(transfer_amount=Decimal("10"), currency="USD", policy=strict)

        assert assessment.band is Band.HIGH
        assert assessment.policy_version == "test/v1"

    def test_defaults_are_declared_as_demo_values(self):
        """The audit must show these were illustrative, not a risk appetite."""
        assert classify(transfer_amount=Decimal("0"), currency="USD").policy_is_demo

    def test_unresolved_terms_are_critical(self):
        assessment = classify(transfer_amount=Decimal("0"), currency="USD", unresolved_terms=2)
        assert assessment.band is Band.CRITICAL
        assert assessment.is_held

    def test_integrity_failure_is_critical_not_merely_high(self):
        assessment = classify(
            transfer_amount=Decimal("0"),
            currency="USD",
            integrity_failures=("Audit chain broken.",),
        )
        assert assessment.band is Band.CRITICAL
        assert assessment.is_held
        assert not assessment.requires_second_approver, (
            "A held decision has no approval path; routing it to a second approver "
            "would ask a person to sign for a number the system cannot vouch for."
        )

    def test_injection_detection_holds_the_decision(self):
        assessment = classify(transfer_amount=Decimal("0"), currency="USD", injection_detected=True)
        assert assessment.is_held

    def test_high_band_requires_a_second_approver(self):
        assert classify(transfer_amount=Decimal("9500000"), currency="USD").requires_second_approver

    def test_every_band_carries_its_reasons(self):
        assessment = classify(transfer_amount=Decimal("9500000"), currency="USD")
        assert assessment.signals
        assert all(s.detail for s in assessment.signals)

    def test_routine_decision_is_low(self):
        assessment = classify(transfer_amount=Decimal("100"), currency="USD")
        assert assessment.band is Band.LOW
        assert not assessment.signals


# ====================================================== §8 maker-checker


class TestMakerChecker:
    def _proposal(self, band=Band.MEDIUM, maker="j.mehta@aether.example"):
        return Proposal(
            decision_id="RUN-STRESS-DEC",
            maker=maker,
            maker_role="RISK",
            assessment=_assessment(band),
        )

    def test_maker_cannot_approve_own_proposal(self):
        proposal = self._proposal()
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                proposal,
                (),
                approver="j.mehta@aether.example",
                role="RISK",
                note="Looks fine.",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "MAKER_CHECKER_VIOLATION"

    def test_holding_both_roles_does_not_make_two_pairs_of_eyes(self):
        """Segregation is on identity, not on role."""
        proposal = self._proposal(maker="dual.role@aether.example")
        with pytest.raises(SupervisionError, match="cannot also"):
            record_approval(
                proposal,
                (),
                approver="dual.role@aether.example",
                role="ADMIN",
                note="Approved under my other hat.",
                occurred_at=STAMP,
            )

    def test_a_different_person_may_approve(self):
        record = record_approval(
            self._proposal(),
            (),
            approver="s.okafor@aether.example",
            role="ADMIN",
            note="Checked against the counterparty statement.",
            occurred_at=STAMP,
        )
        assert record.sequence == 1

    @pytest.mark.parametrize("role", ["LEGAL", "AUDITOR", "GUEST", ""])
    def test_roles_that_may_not_sign_are_refused(self, role):
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                self._proposal(),
                (),
                approver="someone@aether.example",
                role=role,
                note="n/a",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "ROLE_NOT_PERMITTED"

    def test_unnamed_approver_is_refused(self):
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                self._proposal(),
                (),
                approver="   ",
                role="RISK",
                note="n/a",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "UNNAMED_APPROVER"

    def test_duplicate_approval_is_refused(self):
        proposal = self._proposal(band=Band.HIGH)
        first = record_approval(
            proposal,
            (),
            approver="s.okafor@aether.example",
            role="ADMIN",
            note="First check.",
            occurred_at=STAMP,
        )
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                proposal,
                (first,),
                approver="s.okafor@aether.example",
                role="ADMIN",
                note="Second check.",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "DUPLICATE_APPROVAL"

    def test_high_band_needs_two_distinct_signatures(self):
        proposal = self._proposal(band=Band.HIGH)
        first = record_approval(
            proposal, (), approver="a@x.example", role="RISK", note="One.", occurred_at=STAMP
        )
        assert state_of(proposal, (first,)) is ApprovalState.REVIEW

        second = record_approval(
            proposal, (first,), approver="b@x.example", role="ADMIN", note="Two.", occurred_at=STAMP
        )
        assert state_of(proposal, (first, second)) is ApprovalState.APPROVED

    def test_extra_signature_beyond_the_requirement_is_refused(self):
        proposal = self._proposal(band=Band.MEDIUM)
        first = record_approval(
            proposal, (), approver="a@x.example", role="RISK", note="One.", occurred_at=STAMP
        )
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                proposal,
                (first,),
                approver="b@x.example",
                role="ADMIN",
                note="Two.",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "ALREADY_APPROVED"

    def test_held_decision_cannot_be_approved_by_anyone(self):
        proposal = self._proposal(band=Band.CRITICAL)
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                proposal,
                (),
                approver="anyone@x.example",
                role="ADMIN",
                note="Overriding.",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "DECISION_HELD"
        assert state_of(proposal, ()) is ApprovalState.HELD

    def test_material_decision_requires_a_written_rationale(self):
        with pytest.raises(SupervisionError) as excinfo:
            record_approval(
                self._proposal(band=Band.HIGH),
                (),
                approver="a@x.example",
                role="RISK",
                note="   ",
                occurred_at=STAMP,
            )
        assert excinfo.value.code == "RATIONALE_REQUIRED"

    def test_approval_never_claims_to_authorise_a_transfer(self):
        record = record_approval(
            self._proposal(),
            (),
            approver="a@x.example",
            role="RISK",
            note="Checked.",
            occurred_at=STAMP,
        )
        assert record.as_payload()["authorises_transfer"] is False

    def test_recorded_timestamp_is_the_one_supplied(self):
        """Replaying an approval must reproduce the same audit hash."""
        record = record_approval(
            self._proposal(),
            (),
            approver="a@x.example",
            role="RISK",
            note="Checked.",
            occurred_at=STAMP,
        )
        assert record.occurred_at == STAMP


# ======================================================== §17 safe mode


class TestIntegrityPreflight:
    def test_clean_run_is_safe(self):
        result = preflight(
            audit_verified=True,
            snapshot_id="MKT-2026-08-17-STRESS",
            snapshot_as_of="2026-08-17",
            valuation_as_of="2026-08-17",
        )
        assert result.is_safe
        assert result.is_clean
        assert result.checks_run >= 6

    def test_broken_audit_chain_blocks(self):
        result = preflight(
            audit_verified=False,
            audit_break_at=7,
            snapshot_id="MKT-X",
        )
        assert not result.is_safe
        assert any(f.code == "AUDIT_CHAIN_BROKEN" for f in result.blocking)

    def test_unresolved_terms_block_calculation(self):
        result = preflight(
            audit_verified=True,
            snapshot_id="MKT-X",
            unresolved_terms=("threshold.party_b",),
        )
        assert not result.is_safe

    def test_stale_snapshot_blocks(self):
        result = preflight(
            audit_verified=True,
            snapshot_id="MKT-X",
            snapshot_as_of="2026-08-14",
            valuation_as_of="2026-08-17",
        )
        assert any(f.code == "STALE_MARKET_SNAPSHOT" for f in result.blocking)

    def test_model_version_mismatch_blocks(self):
        result = preflight(
            audit_verified=True,
            snapshot_id="MKT-X",
            expected_registry_key="model@v2+p2+pol1",
            actual_registry_key="model@v1+p1+pol1",
        )
        assert any(f.code == "MODEL_VERSION_MISMATCH" for f in result.blocking)

    def test_unavailable_model_degrades_rather_than_blocks(self):
        """Replay is a recorded prior result, not a compromised one."""
        result = preflight(
            audit_verified=True,
            snapshot_id="MKT-X",
            model_available=False,
            model_reason="No card is DEPLOYED.",
        )
        assert result.is_safe
        assert not result.is_clean

    def test_hostile_document_blocks_and_suspicious_degrades(self):
        hostile = preflight(audit_verified=True, snapshot_id="MKT-X", injection_severity="HOSTILE")
        suspicious = preflight(
            audit_verified=True, snapshot_id="MKT-X", injection_severity="SUSPICIOUS"
        )
        assert not hostile.is_safe
        assert suspicious.is_safe and not suspicious.is_clean

    def test_every_failure_carries_a_remedy(self):
        """A finding a person cannot act on is a dead end."""
        result = preflight(audit_verified=False, snapshot_id=None)
        assert result.failures
        for failure in result.failures:
            assert failure.remedy, f"{failure.code} has no remedy."

    def test_failures_feed_escalation_as_critical(self):
        result = preflight(audit_verified=False, snapshot_id="MKT-X")
        assessment = classify(
            transfer_amount=Decimal("0"),
            currency="USD",
            integrity_failures=result.as_escalation_signals(),
        )
        assert assessment.is_held

    def test_there_is_no_severity_that_does_nothing(self):
        assert set(IntegritySeverity) == {
            IntegritySeverity.BLOCKING,
            IntegritySeverity.DEGRADED,
        }


# ========================================================= §13 evidence


class TestEvidencePack:
    RUN: ClassVar[dict[str, object]] = {
        "run_id": "RUN-STRESS",
        "trace_id": "RUN-STRESS",
        "as_of": "2026-08-17",
        "engine_version": "0.1.0",
        "snapshot": {"snapshot_id": "MKT-2026-08-17-STRESS", "as_of": "2026-08-17"},
        "agreement": {"agreement_id": "CSA-MERIDIAN-2026", "terms_version": 1},
        "exposure": {"netting_set_id": "NS-MERIDIAN-001", "trade_count": 8},
        "margin_call": {
            "call_amount": {"amount": "9500000.00", "currency": "USD"},
            "waterfall": [{"label": "Threshold", "clause": "Paragraph 11(b)(iii)(A)"}],
        },
        "allocation": {"status": "OPTIMAL", "lines": [], "considered": [], "shadow_prices": []},
        "decision": {"decision_id": "RUN-STRESS-DEC", "action": "POST_COLLATERAL"},
        "audit": {"chain_id": "RUN-STRESS", "head_hash": "abc", "verified": True, "events": []},
    }

    def test_pack_answers_all_seven_questions(self):
        pack = build_pack(run=self.RUN).as_payload()

        for section in (
            "what_happened",
            "which_model",
            "which_clause",
            "who_reviewed",
            "what_calculation",
            "why_collateral",
            "who_approved",
        ):
            assert section in pack, f"Evidence pack cannot answer: {section}"

    def test_pack_is_self_hashing(self):
        pack = build_pack(run=self.RUN)
        assert pack.pack_hash == content_hash(pack.body)

    def test_identical_input_produces_an_identical_pack_hash(self):
        assert build_pack(run=self.RUN).pack_hash == build_pack(run=self.RUN).pack_hash

    def test_altering_the_run_changes_the_pack_hash(self):
        tampered = {
            **self.RUN,
            "margin_call": {
                **self.RUN["margin_call"],
                "call_amount": {"amount": "1.00", "currency": "USD"},
            },
        }
        assert build_pack(run=tampered).pack_hash != build_pack(run=self.RUN).pack_hash

    def test_pack_carries_the_lineage_hashes(self):
        hashes = build_pack(run=self.RUN).body["lineage"]["hashes"]
        for stage in (
            "frozen_agreement",
            "market_snapshot",
            "risk_engine_inputs",
            "risk_engine_output",
            "final_decision",
        ):
            assert hashes[stage], f"No hash captured for {stage}."

    def test_pack_does_not_claim_immutability(self):
        note = build_pack(run=self.RUN).body["lineage"]["integrity_note"]
        assert "detectable" in note
        assert "does not make the store immutable" in note

    def test_pack_does_not_claim_compliance(self):
        disclaimer = build_pack(run=self.RUN).body["disclaimer"]
        assert "No regulatory approval" in disclaimer
        assert "SIMULATED" in disclaimer

    def test_missing_allocation_is_stated_not_faked(self):
        run = {**self.RUN, "allocation": None}
        why = build_pack(run=run).body["why_collateral"]

        assert why["status"] == "NOT_REQUIRED"
        assert "different from an allocation of zero" in why["note"]

    def test_approvals_never_claim_to_authorise_a_transfer(self):
        pack = build_pack(
            run=self.RUN,
            approvals=({"approver": "a@x", "role": "RISK"},),
        )
        assert pack.body["who_approved"]["authorises_transfer"] is False
