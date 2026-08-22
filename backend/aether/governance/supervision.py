"""Who may propose, who may approve, and that they are not the same person.

.. rubric:: The control

Separation of duties is the oldest control in banking operations and the one most
often lost to a convenience shortcut. AETHER's claim is that the same person must
not interpret the contract, compute the margin, and sign off the transfer. This
module is where that stops being a claim.

Three rules, and they compose:

**Maker ≠ checker.** The person who proposed a decision may not approve it. This
is checked on identity, not on role: a user holding both RISK and APPROVER is
still one pair of eyes.

**Four eyes on material decisions.** A ``HIGH`` band decision needs two distinct
approvers. The second is not a rubber stamp on the first — each records their own
rationale, and the decision is not approved until both are present.

**No approval under hold.** A ``CRITICAL`` decision has no approval path. It is
not escalated to someone more senior; it is stopped until the condition clears.
Anything else turns an integrity failure into a signature.

.. rubric:: Why identity and not session

An approval names a person. It records who they were, when they acted and what
they said — and that record is what an evidence pack shows a supervisor a year
later. A session token proves someone was logged in; it does not name them, and
"the RISK role approved this" is not an audit record.

.. rubric:: What this module does not do

It does not authenticate. It is handed an identity by the layer above and takes
it at face value, so the strength of this control is exactly the strength of the
identity layer in front of it. In the current prototype that layer is a role
selected in the browser, which means these rules demonstrate the mechanism rather
than resist a determined insider. That gap is stated in the audit rather than
papered over.

Pure: no I/O, no network, no clock. Timestamps arrive from the caller so that
replaying an approval reproduces the same audit hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aether.governance.escalation import Assessment, Band

__all__ = [
    "APPROVER_ROLES",
    "ApprovalRecord",
    "ApprovalState",
    "Proposal",
    "SupervisionError",
    "record_approval",
    "state_of",
]

#: Roles permitted to sign off a margin decision.
#:
#: LEGAL interprets the contract and AUDITOR reads the record; neither signs for
#: money. Kept here rather than in the API so the rule has one home.
APPROVER_ROLES: frozenset[str] = frozenset({"RISK", "ADMIN"})


class ApprovalState(StrEnum):
    """Where a decision stands.

    ``PROPOSED → REVIEW → APPROVED | REJECTED``, with ``HELD`` sitting outside the
    path: a held decision is not partway to approval, it is stopped.
    """

    PROPOSED = "PROPOSED"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HELD = "HELD"
    NOT_REQUIRED = "NOT_REQUIRED"


class SupervisionError(RuntimeError):
    """A supervision rule refused the action.

    ``code`` is stable and machine-readable so the API can map it to a status and
    a test can assert on it without matching prose.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Proposal:
    """A decision awaiting authorisation.

    ``maker`` is whoever caused the proposal to exist. For an engine-generated
    margin call that is the person who ran it — a decision nobody asked for is a
    decision nobody is accountable for.
    """

    decision_id: str
    maker: str
    maker_role: str
    assessment: Assessment


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """One signature."""

    approver: str
    role: str
    note: str
    occurred_at: str
    decision_id: str
    #: 1 for the first signature, 2 for the second on a four-eyes decision.
    sequence: int

    def as_payload(self) -> dict[str, object]:
        return {
            "approver": self.approver,
            "role": self.role,
            "note": self.note,
            "occurred_at": self.occurred_at,
            "decision_id": self.decision_id,
            "sequence": self.sequence,
            "authorises_transfer": False,
        }


def _required_signatures(assessment: Assessment) -> int:
    return 2 if assessment.requires_second_approver else 1


def state_of(
    proposal: Proposal,
    approvals: tuple[ApprovalRecord, ...],
    *,
    rejected: bool = False,
) -> ApprovalState:
    """Where this decision stands given the signatures so far."""
    if rejected:
        return ApprovalState.REJECTED
    if proposal.assessment.is_held:
        return ApprovalState.HELD
    if len(approvals) >= _required_signatures(proposal.assessment):
        return ApprovalState.APPROVED
    if approvals:
        return ApprovalState.REVIEW
    return ApprovalState.PROPOSED


def record_approval(
    proposal: Proposal,
    existing: tuple[ApprovalRecord, ...],
    *,
    approver: str,
    role: str,
    note: str,
    occurred_at: str,
) -> ApprovalRecord:
    """Validate and build one signature, or refuse with a reason.

    Every rule that could stop an approval is applied here, in the order a person
    would ask them: are you allowed to sign at all, is this decision signable, are
    you the person who proposed it, and have you already signed.
    """
    approver = approver.strip()
    if not approver:
        raise SupervisionError(
            "UNNAMED_APPROVER",
            "An approval must name the person who gave it. An unnamed signature is "
            "not an audit record.",
        )

    if role not in APPROVER_ROLES:
        raise SupervisionError(
            "ROLE_NOT_PERMITTED",
            f"Role '{role}' cannot approve a margin decision. Permitted: "
            f"{', '.join(sorted(APPROVER_ROLES))}. Interpreting the contract and "
            "signing off the money it produces are different jobs.",
        )

    # A held decision has no approval path. Checked before maker-checker so the
    # refusal names the real reason rather than an incidental one.
    if proposal.assessment.is_held:
        reasons = "; ".join(s.detail for s in proposal.assessment.signals)
        raise SupervisionError(
            "DECISION_HELD",
            f"Decision {proposal.decision_id} is held and cannot be approved. "
            f"{reasons} Clear the condition rather than overriding the hold.",
        )

    if approver == proposal.maker:
        raise SupervisionError(
            "MAKER_CHECKER_VIOLATION",
            f"{approver} proposed decision {proposal.decision_id} and cannot also "
            "approve it. A second person must check the work — holding both roles "
            "does not make one pair of eyes into two.",
        )

    if any(record.approver == approver for record in existing):
        raise SupervisionError(
            "DUPLICATE_APPROVAL",
            f"{approver} has already signed decision {proposal.decision_id}. A "
            "four-eyes decision needs two distinct people, not one person twice.",
        )

    required = _required_signatures(proposal.assessment)
    if len(existing) >= required:
        raise SupervisionError(
            "ALREADY_APPROVED",
            f"Decision {proposal.decision_id} already carries {len(existing)} of "
            f"{required} required signature(s). Withdraw an approval before adding "
            "another.",
        )

    if not note.strip() and proposal.assessment.band in {Band.HIGH, Band.MEDIUM}:
        raise SupervisionError(
            "RATIONALE_REQUIRED",
            f"Decision {proposal.decision_id} is banded "
            f"{proposal.assessment.band.value} and requires a written rationale. "
            "A signature without a reason tells a reviewer nothing.",
        )

    return ApprovalRecord(
        approver=approver,
        role=role,
        note=note,
        occurred_at=occurred_at,
        decision_id=proposal.decision_id,
        sequence=len(existing) + 1,
    )
