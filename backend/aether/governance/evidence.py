"""The Supervisory Evidence Pack.

.. rubric:: The seven questions

A supervisor looking at one decision, months later, asks the same seven things:

    What happened?  ·  Which model produced it?  ·  Which clause was used?
    Who reviewed it?  ·  What calculation produced the result?
    Why this collateral?  ·  Who approved it?

An evidence pack answers all seven from one record, and each answer carries the
hash of the artefact it came from, so a reader can tell whether what they are
looking at is what was there at the time.

.. rubric:: Assembled, never re-derived

Every field is copied from something the run already produced. This module runs
no calculation, calls no model and re-reads no fixture: if it recomputed anything,
the pack would be evidence of *this* execution rather than of the decision it
claims to describe.

That is also why the pack carries the run's own audit chain rather than a summary
of it. A summary is an assertion; the chain is checkable.

.. rubric:: On hashing

The chain makes tampering **detectable**, not impossible. Altering a stored event
invalidates every hash after it, and :meth:`AuditChain.verify` finds the first
break. It does not prevent someone with write access from rewriting the whole
chain, and this module does not pretend otherwise — a single-writer hash chain is
tamper-evident, and calling it immutable would be a claim the architecture cannot
support. Durable independent storage is where that gap closes, and it is listed as
outstanding rather than implied here.

Pure: no I/O, no network, no clock.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from aether.core.audit import canonical_json

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "EvidencePack",
    "build_pack",
    "content_hash",
]

#: Bumped whenever the shape below changes, so a stored pack can be read by the
#: reader that understands it rather than guessed at.
EVIDENCE_SCHEMA_VERSION = "evidence/v1"


def content_hash(payload: Any) -> str:
    """SHA-256 over the canonical form of a payload.

    Reuses ``core.audit.canonical_json`` — sorted keys, compact separators,
    Decimal as string, floats refused — so a hash computed here matches one
    computed in the audit chain for the same content. Two hashing conventions in
    one system means two hashes that disagree for no reason anybody can find.
    """
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidencePack:
    """One decision, with everything needed to reconstruct it."""

    schema_version: str
    decision_id: str
    #: Hash over the pack's own body, so the pack itself is checkable.
    pack_hash: str
    body: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "pack_hash": self.pack_hash,
            **self.body,
        }


def build_pack(
    *,
    run: dict[str, Any],
    extraction: dict[str, Any] | None = None,
    document_text: str | None = None,
    sanitisation: dict[str, Any] | None = None,
    attribution: dict[str, Any] | None = None,
    escalation: dict[str, Any] | None = None,
    preflight: dict[str, Any] | None = None,
    approvals: tuple[dict[str, Any], ...] = (),
    exported_by: str = "",
    exported_at: str = "",
) -> EvidencePack:
    """Assemble the pack for one decision.

    ``run`` is the serialised pipeline result — the same payload the dashboard
    renders. Everything else is optional because a pack for a run whose terms came
    from the committed fixture genuinely has no extraction to show, and inventing
    an empty section would suggest one existed.
    """
    decision = run.get("decision", {})
    agreement = run.get("agreement", {})
    exposure = run.get("exposure", {})
    margin_call = run.get("margin_call", {})
    allocation = run.get("allocation")
    audit = run.get("audit", {})
    snapshot = run.get("snapshot", {})

    # ---- 1. What happened
    what_happened = {
        "action": decision.get("action"),
        "status": decision.get("status"),
        "headline": decision.get("headline"),
        "amount": decision.get("amount"),
        "transferor": decision.get("transferor"),
        "rationale": decision.get("rationale", []),
        "as_of": run.get("as_of"),
        "run_id": run.get("run_id"),
        "trace_id": run.get("trace_id"),
        "requires_human_approval": decision.get("requires_human_approval"),
    }

    # ---- 2. Which model produced it
    which_model = {
        "attribution": attribution,
        "terms_source": run.get("terms_source"),
        "note": (
            "Absent when the run computed on the committed agreement fixture rather "
            "than on a model-produced extraction."
            if attribution is None
            else None
        ),
    }

    # ---- 3. Which clause was used
    fields = (extraction or {}).get("fields", [])
    which_clause = {
        "agreement_id": agreement.get("agreement_id"),
        "terms_version": agreement.get("terms_version"),
        "governing_law": agreement.get("governing_law"),
        "document_sha256": (extraction or {}).get("document_sha256"),
        "document_hash_recomputed": (
            hashlib.sha256(document_text.encode("utf-8")).hexdigest()
            if document_text is not None
            else None
        ),
        "sanitisation": sanitisation,
        "citations": [
            {
                "path": f.get("path"),
                "value": f.get("value"),
                "confidence": f.get("confidence"),
                "citation": f.get("citation"),
            }
            for f in fields
            if f.get("citation")
        ],
        "waterfall_clauses": [
            {"label": step.get("label"), "clause": step.get("clause")}
            for step in margin_call.get("waterfall", [])
        ],
    }

    # ---- 4. Who reviewed it
    who_reviewed = {
        "reviewed_fields": [
            {
                "path": f.get("path"),
                "reviewer": f.get("reviewer"),
                "rationale": f.get("reviewer_rationale"),
                "source": f.get("source"),
                "review_reason": f.get("review_reason"),
            }
            for f in fields
            if f.get("source") == "HUMAN"
        ],
        "outstanding": [f.get("path") for f in fields if not f.get("is_resolved", True)],
        "confidence_threshold": (extraction or {}).get("confidence_threshold"),
        "mean_confidence": (extraction or {}).get("mean_confidence"),
    }

    # ---- 5. What calculation produced the result
    what_calculation = {
        "engine_version": run.get("engine_version"),
        "market_snapshot": {
            "snapshot_id": snapshot.get("snapshot_id"),
            "label": snapshot.get("label"),
            "as_of": snapshot.get("as_of"),
            "simulated": snapshot.get("simulated"),
        },
        "inputs": {
            "netting_set_id": exposure.get("netting_set_id"),
            "trade_count": exposure.get("trade_count"),
            "threshold": margin_call.get("threshold"),
            "independent_amount": margin_call.get("independent_amount"),
            "minimum_transfer_amount": margin_call.get("minimum_transfer_amount"),
            "posted_value": margin_call.get("posted_value"),
            "mta_before_rounding": margin_call.get("mta_before_rounding"),
        },
        "outputs": {
            "exposure": exposure.get("exposure"),
            "gross_positive": exposure.get("gross_positive"),
            "netting_benefit": exposure.get("netting_benefit"),
            "credit_support_amount": margin_call.get("credit_support_amount"),
            "unrounded_amount": margin_call.get("unrounded_amount"),
            "call_amount": margin_call.get("call_amount"),
            "direction": margin_call.get("direction"),
            "gated_by_mta": margin_call.get("gated_by_mta"),
        },
        "waterfall": margin_call.get("waterfall", []),
    }

    # ---- 6. Why this collateral
    why_collateral = (
        {
            "status": allocation.get("status"),
            "required_value": allocation.get("required_value"),
            "allocated_value": allocation.get("allocated_value"),
            "total_cost": allocation.get("total_cost"),
            "baseline_cost": allocation.get("baseline_cost"),
            "saving": allocation.get("saving"),
            "baseline_covers_requirement": allocation.get("baseline_covers_requirement"),
            "selected": [
                {
                    "asset_id": line.get("asset_id"),
                    "description": line.get("description"),
                    "asset_class": line.get("asset_class"),
                    "market_value_posted": line.get("market_value_posted"),
                    "effective_percentage": line.get("effective_percentage"),
                    "effective_value": line.get("effective_value"),
                    "cost_per_effective_unit_bps": line.get("cost_per_effective_unit_bps"),
                }
                for line in allocation.get("lines", [])
            ],
            "rejected": [
                {
                    "asset_id": line.get("asset_id"),
                    "reason": line.get("not_selected_reason"),
                }
                for line in allocation.get("considered", [])
                if not line.get("selected")
            ],
            "excluded": allocation.get("excluded", []),
            "binding_constraints": [
                {
                    "name": price.get("name"),
                    "description": price.get("description"),
                    "shadow_price_bps": price.get("shadow_price_bps"),
                }
                for price in allocation.get("shadow_prices", [])
                if price.get("binding")
            ],
        }
        if allocation
        else {
            "status": "NOT_REQUIRED",
            "note": (
                "No Delivery Amount was due at this snapshot, so the optimiser was "
                "not invoked. That is different from an allocation of zero."
            ),
        }
    )

    # ---- 7. Who approved it
    who_approved = {
        "escalation": escalation,
        "preflight": preflight,
        "approvals": list(approvals),
        "signatures_present": len(approvals),
        "authorises_transfer": False,
        "note": (
            "An approval is a record that a named person accepted the engine's "
            "proposal. AETHER holds no settlement connectivity and transmits "
            "nothing."
        ),
    }

    # ---- lineage
    lineage = {
        "chain_id": audit.get("chain_id"),
        "head_hash": audit.get("head_hash"),
        "verified": audit.get("verified"),
        "break_at": audit.get("break_at"),
        "verification_message": audit.get("verification_message"),
        "event_count": len(audit.get("events", [])),
        "events": audit.get("events", []),
        "hashes": {
            "source_document": (extraction or {}).get("document_sha256"),
            "extracted_terms": content_hash(fields) if fields else None,
            "human_review": (
                content_hash(who_reviewed["reviewed_fields"])
                if who_reviewed["reviewed_fields"]
                else None
            ),
            "frozen_agreement": content_hash(agreement) if agreement else None,
            "market_snapshot": content_hash(snapshot) if snapshot else None,
            "risk_engine_inputs": content_hash(what_calculation["inputs"]),
            "risk_engine_output": content_hash(what_calculation["outputs"]),
            "optimizer_inputs": (
                content_hash(allocation.get("considered", [])) if allocation else None
            ),
            "optimizer_output": (content_hash(allocation.get("lines", [])) if allocation else None),
            "approval": content_hash(list(approvals)) if approvals else None,
            "final_decision": content_hash(decision) if decision else None,
        },
        "integrity_note": (
            "Each event hashes its own canonical content plus its predecessor, so "
            "altering any record invalidates every hash after it. This makes "
            "tampering detectable. It does not make the store immutable, and no "
            "such claim is made."
        ),
    }

    body: dict[str, Any] = {
        "exported_by": exported_by,
        "exported_at": exported_at,
        "simulated": True,
        "disclaimer": (
            "SIMULATED DATA. Designed to support supervised AI governance, "
            "auditability, model governance, human oversight and regulatory review. "
            "No regulatory approval, certification or compliance is claimed."
        ),
        "what_happened": what_happened,
        "which_model": which_model,
        "which_clause": which_clause,
        "who_reviewed": who_reviewed,
        "what_calculation": what_calculation,
        "why_collateral": why_collateral,
        "who_approved": who_approved,
        "lineage": lineage,
    }

    return EvidencePack(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        decision_id=str(decision.get("decision_id", run.get("run_id", "unknown"))),
        pack_hash=content_hash(body),
        body=body,
    )
