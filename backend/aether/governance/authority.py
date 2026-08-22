"""What each component is permitted to do.

.. rubric:: Why this exists when the tool boundary already exists

``aether.agents.orchestrator`` already makes it impossible for an agent to *pass*
a number: ``Argument = str | int | bool | None`` rejects a ``Decimal`` at
construction. That is a strong control and it is not duplicated here.

What it does not cover is which component may *invoke* which capability. A Legal
agent cannot pass a margin figure, but nothing structurally stopped it from
calling the margin tool. This module names every capability in the system,
declares which actor holds it, and refuses the call otherwise — at the service
layer, where it applies to any caller, rather than in the interface, where it
applies only to the browser we shipped.

.. rubric:: The matrix is the specification

:data:`AUTHORITY` is the machine-readable form of §4 of the governance spec. It
is written as data rather than as ``if`` statements so that a reviewer can read
the policy without reading the code that applies it, and so a test can assert the
two agree.

.. rubric:: Deny by default

An actor holds a capability only if the matrix grants it. An unrecognised actor
holds nothing, and an unrecognised capability is refused rather than allowed —
because the failure mode of "allow what I don't recognise" in a financial control
is unbounded.

Pure: no I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "AUTHORITY",
    "Actor",
    "AuthorityError",
    "Capability",
    "capabilities_of",
    "holders_of",
    "may",
    "require",
]


class Actor(StrEnum):
    """Who is asking. Components and humans are the same kind of thing here.

    A human role is an actor because the point of the matrix is that a human and
    an agent are subject to one policy, expressed once. Splitting them into two
    systems is how a gap opens between them.
    """

    LEGAL_AGENT = "LEGAL_AGENT"
    RISK_ENGINE = "RISK_ENGINE"
    COLLATERAL_OPTIMIZER = "COLLATERAL_OPTIMIZER"
    DESK_ASSISTANT = "DESK_ASSISTANT"

    HUMAN_LEGAL = "HUMAN_LEGAL"
    HUMAN_RISK = "HUMAN_RISK"
    HUMAN_APPROVER = "HUMAN_APPROVER"
    HUMAN_AUDITOR = "HUMAN_AUDITOR"
    HUMAN_ADMIN = "HUMAN_ADMIN"


class Capability(StrEnum):
    """Every action the system can be asked to perform.

    Named for the effect, not the endpoint, so that adding a second route to the
    same effect does not create a second policy.
    """

    # ---- interpretation
    READ_DOCUMENT = "READ_DOCUMENT"
    EXTRACT_TERMS = "EXTRACT_TERMS"
    CITE_SOURCE = "CITE_SOURCE"
    FLAG_AMBIGUITY = "FLAG_AMBIGUITY"
    CONFIRM_TERM = "CONFIRM_TERM"
    FREEZE_AGREEMENT = "FREEZE_AGREEMENT"

    # ---- calculation
    READ_FROZEN_AGREEMENT = "READ_FROZEN_AGREEMENT"
    READ_MARKET_SNAPSHOT = "READ_MARKET_SNAPSHOT"
    COMPUTE_EXPOSURE = "COMPUTE_EXPOSURE"
    COMPUTE_MARGIN = "COMPUTE_MARGIN"

    # ---- collateral
    EVALUATE_ELIGIBILITY = "EVALUATE_ELIGIBILITY"
    OPTIMISE_ALLOCATION = "OPTIMISE_ALLOCATION"
    PROPOSE_COLLATERAL = "PROPOSE_COLLATERAL"

    # ---- authorisation
    APPROVE_DECISION = "APPROVE_DECISION"
    REJECT_DECISION = "REJECT_DECISION"
    EXECUTE_SETTLEMENT = "EXECUTE_SETTLEMENT"

    # ---- oversight
    READ_AUDIT = "READ_AUDIT"
    EXPORT_EVIDENCE = "EXPORT_EVIDENCE"
    CONFIGURE_SYSTEM = "CONFIGURE_SYSTEM"
    PROMOTE_MODEL = "PROMOTE_MODEL"


#: The authority matrix — §4 as data.
#:
#: Three properties are worth stating because they are the argument:
#:
#: * **No AI actor holds** ``APPROVE_DECISION``, ``FREEZE_AGREEMENT``,
#:   ``CONFIRM_TERM`` or ``EXECUTE_SETTLEMENT``. Authorisation is human-only, by
#:   construction rather than by configuration.
#: * **No actor at all holds** ``EXECUTE_SETTLEMENT``. AETHER generates
#:   instructions in message shape and has no connectivity; granting the
#:   capability to anyone would imply otherwise.
#: * **The Legal agent cannot reach a calculation** and the Risk engine cannot
#:   reach an interpretation. That separation is the "AI interprets, engines
#:   calculate" claim, expressed as a permission rather than a convention.
AUTHORITY: dict[Actor, frozenset[Capability]] = {
    Actor.LEGAL_AGENT: frozenset(
        {
            Capability.READ_DOCUMENT,
            Capability.EXTRACT_TERMS,
            Capability.CITE_SOURCE,
            Capability.FLAG_AMBIGUITY,
        }
    ),
    Actor.RISK_ENGINE: frozenset(
        {
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_MARKET_SNAPSHOT,
            Capability.COMPUTE_EXPOSURE,
            Capability.COMPUTE_MARGIN,
        }
    ),
    Actor.COLLATERAL_OPTIMIZER: frozenset(
        {
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_MARKET_SNAPSHOT,
            Capability.EVALUATE_ELIGIBILITY,
            Capability.OPTIMISE_ALLOCATION,
            Capability.PROPOSE_COLLATERAL,
        }
    ),
    # Reads what is already on the user's screen. Holds no capability that
    # changes anything, including READ_DOCUMENT: the assistant answers about a
    # run, and giving it the raw contract would put untrusted text into a second
    # model context for no benefit.
    Actor.DESK_ASSISTANT: frozenset(
        {
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_MARKET_SNAPSHOT,
        }
    ),
    Actor.HUMAN_LEGAL: frozenset(
        {
            Capability.READ_DOCUMENT,
            Capability.CITE_SOURCE,
            Capability.CONFIRM_TERM,
            Capability.FREEZE_AGREEMENT,
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_AUDIT,
        }
    ),
    Actor.HUMAN_RISK: frozenset(
        {
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_MARKET_SNAPSHOT,
            Capability.COMPUTE_EXPOSURE,
            Capability.COMPUTE_MARGIN,
            Capability.EVALUATE_ELIGIBILITY,
            Capability.OPTIMISE_ALLOCATION,
            Capability.PROPOSE_COLLATERAL,
            Capability.READ_AUDIT,
            Capability.EXPORT_EVIDENCE,
        }
    ),
    Actor.HUMAN_APPROVER: frozenset(
        {
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_MARKET_SNAPSHOT,
            Capability.APPROVE_DECISION,
            Capability.REJECT_DECISION,
            Capability.READ_AUDIT,
            Capability.EXPORT_EVIDENCE,
        }
    ),
    # Read-only by construction. An auditor who can change what they audit is
    # not an auditor.
    Actor.HUMAN_AUDITOR: frozenset(
        {
            Capability.READ_FROZEN_AGREEMENT,
            Capability.READ_MARKET_SNAPSHOT,
            Capability.READ_AUDIT,
            Capability.EXPORT_EVIDENCE,
        }
    ),
    Actor.HUMAN_ADMIN: frozenset(
        {
            Capability.READ_AUDIT,
            Capability.EXPORT_EVIDENCE,
            Capability.CONFIGURE_SYSTEM,
            Capability.PROMOTE_MODEL,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class AuthorityError(Exception):
    """Raised when an actor attempts something it does not hold.

    Carries the actor, the capability and who does hold it, because a refusal a
    user cannot act on is a dead end. The message never reveals the value that
    was being protected.
    """

    actor: str
    capability: str
    holders: tuple[str, ...]

    def __str__(self) -> str:
        who = ", ".join(self.holders) if self.holders else "no actor in this system"
        return f"{self.actor} does not hold {self.capability}. Held by: {who}."


def capabilities_of(actor: Actor | str) -> frozenset[Capability]:
    """What this actor holds. An unknown actor holds nothing."""
    try:
        resolved = Actor(actor)
    except ValueError:
        return frozenset()
    return AUTHORITY.get(resolved, frozenset())


def holders_of(capability: Capability | str) -> tuple[str, ...]:
    """Every actor holding this capability, for a refusal message."""
    try:
        resolved = Capability(capability)
    except ValueError:
        return ()
    return tuple(sorted(actor.value for actor, held in AUTHORITY.items() if resolved in held))


def may(actor: Actor | str, capability: Capability | str) -> bool:
    """Whether this actor may do this. Deny by default.

    An unrecognised capability is denied rather than allowed: a typo in a
    capability name must fail closed, not open.
    """
    try:
        resolved_capability = Capability(capability)
    except ValueError:
        return False
    return resolved_capability in capabilities_of(actor)


def require(actor: Actor | str, capability: Capability | str) -> None:
    """Assert the actor holds the capability, or raise.

    The enforcement point. Call it at the service boundary — before the work,
    not after — so that a refusal costs nothing and leaks nothing.
    """
    if not may(actor, capability):
        actor_name = actor.value if isinstance(actor, Actor) else str(actor)
        capability_name = (
            capability.value if isinstance(capability, Capability) else str(capability)
        )
        raise AuthorityError(
            actor=actor_name,
            capability=capability_name,
            holders=holders_of(capability),
        )
