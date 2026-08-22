"""The AI model registry.

Every AI invocation in AETHER must be attributable to a registered model, at a
registered version, under a registered prompt and policy. The question this module
exists to answer is:

    "Which model, version and policy produced this output?"

and the answer has to survive the model being upgraded, so it is recorded *onto
the output* rather than looked up later from whatever is deployed now.

.. rubric:: Why a registry rather than a settings string

``AETHER_MODEL_ID`` says which model is configured. It cannot say whether that
model has been evaluated, what it is approved to do, what it is forbidden to do,
or whether a historical decision was produced by it or by its predecessor. A
settings string is configuration; this is a control.

.. rubric:: Change control

A model is not deployed by editing a variable. :class:`DeploymentStatus` moves
through the states in :data:`PROMOTION_PATH`, and :func:`resolve` refuses to serve
anything that has not reached ``DEPLOYED``. That makes the workflow in §12
mechanical rather than procedural::

    REGISTERED → EVALUATED → SECURITY_TESTED → REGRESSION_TESTED
               → APPROVED → DEPLOYED

Promotion is recorded here as data. The *act* of approving a promotion is a human
decision and is not automated by this module — :func:`promote` refuses a skipped
step and refuses an unnamed approver, and that is the whole of what it enforces.

.. rubric:: What this does not do

It does not evaluate a model, run its security tests, or verify that the claims in
a card are true. A card records what a human asserted at a point in time. The
evaluation harness in ``aether.agents.evaluation`` measures extraction quality
against ground truth; wiring its result into ``evaluation_status`` is a deployment
step, not something this module can do on its own.

Pure: no I/O, no network, no clock. Timestamps are authored into the card, never
read from the system.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

__all__ = [
    "PROMOTION_PATH",
    "REGISTRY",
    "Attribution",
    "DeploymentStatus",
    "EvaluationStatus",
    "ModelCard",
    "ModelNotDeployedError",
    "UseCase",
    "attribute",
    "cards",
    "promote",
    "resolve",
]


class UseCase(StrEnum):
    """What a registered model is approved to be used for.

    A model approved to read a contract is not thereby approved to talk to a user.
    The two carry different risks and are registered separately.
    """

    #: Extract typed contractual terms from a Credit Support Annex.
    LEGAL_CLAUSE_EXTRACTION = "LEGAL_CLAUSE_EXTRACTION"
    #: Answer a desk user's questions over deterministic tools.
    DESK_ASSISTANCE = "DESK_ASSISTANCE"


class EvaluationStatus(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DeploymentStatus(StrEnum):
    REGISTERED = "REGISTERED"
    EVALUATED = "EVALUATED"
    SECURITY_TESTED = "SECURITY_TESTED"
    REGRESSION_TESTED = "REGRESSION_TESTED"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    #: Withdrawn from service. Historical decisions keep their attribution.
    RETIRED = "RETIRED"


#: The order a model must move through. A step may not be skipped.
PROMOTION_PATH: tuple[DeploymentStatus, ...] = (
    DeploymentStatus.REGISTERED,
    DeploymentStatus.EVALUATED,
    DeploymentStatus.SECURITY_TESTED,
    DeploymentStatus.REGRESSION_TESTED,
    DeploymentStatus.APPROVED,
    DeploymentStatus.DEPLOYED,
)


class ModelNotDeployedError(RuntimeError):
    """Raised when a use case has no model cleared to serve it."""

    def __init__(self, use_case: UseCase, reason: str) -> None:
        super().__init__(reason)
        self.use_case = use_case
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ModelCard:
    """One registered model, at one version, for one use case."""

    model_id: str
    provider: str
    model_version: str
    prompt_version: str
    policy_version: str
    approved_use_case: UseCase

    #: What this model is relied on to do. Descriptive, for a reviewer.
    capabilities: tuple[str, ...]
    #: What it must never do. Each entry is enforced elsewhere — in the tool
    #: argument types, the authority matrix, or the freeze gate — and is listed
    #: here so a reviewer can find the enforcement point.
    prohibited_actions: tuple[str, ...]

    evaluation_status: EvaluationStatus
    deployment_status: DeploymentStatus

    #: Authored, not observed. ISO-8601.
    created_at: str
    updated_at: str

    #: Free text: what changed in this version and why it was promoted.
    change_note: str = ""

    @property
    def key(self) -> str:
        """Stable identity of this exact model/prompt/policy combination."""
        return f"{self.model_id}@{self.model_version}+{self.prompt_version}+{self.policy_version}"

    @property
    def is_servable(self) -> bool:
        return (
            self.deployment_status is DeploymentStatus.DEPLOYED
            and self.evaluation_status is EvaluationStatus.PASSED
        )


@dataclass(frozen=True, slots=True)
class Attribution:
    """Stamped onto every AI-produced output.

    Carried with the output into the audit chain, so a decision made a year ago
    still names the model that produced it even after that model is retired.
    """

    model_id: str
    provider: str
    model_version: str
    prompt_version: str
    policy_version: str
    use_case: UseCase
    #: ``replay`` or ``live``. A replayed extraction was not produced by a model
    #: call in this run, and saying otherwise would misattribute it.
    mode: str
    registry_key: str

    def as_payload(self) -> dict[str, str]:
        """JSON-safe, for the audit chain and the evidence pack."""
        return {
            "model_id": self.model_id,
            "provider": self.provider,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "policy_version": self.policy_version,
            "use_case": self.use_case.value,
            "mode": self.mode,
            "registry_key": self.registry_key,
        }


# ----------------------------------------------------------------- the registry

#: The registered models.
#:
#: Authored rather than discovered: a model appears here because a person put it
#: here, which is the point. ``policy_version`` names the governance policy the
#: card was registered under, so tightening the policy invalidates cards that
#: were approved under the old one rather than silently grandfathering them.
REGISTRY: tuple[ModelCard, ...] = (
    ModelCard(
        model_id="claude-opus-5",
        provider="anthropic",
        model_version="claude-opus-5",
        prompt_version="legal-clause/v1",
        policy_version="aether-ai-policy/v1",
        approved_use_case=UseCase.LEGAL_CLAUSE_EXTRACTION,
        capabilities=(
            "Read a Credit Support Annex and emit typed contractual terms",
            "Quote the verbatim clause supporting each extracted value",
            "Report calibrated confidence per field",
            "Flag ambiguity, conditionality and conflicting clauses for a human",
        ),
        prohibited_actions=(
            "Compute any monetary amount "
            "(enforced: aether.agents.orchestrator.Argument rejects Decimal)",
            "Produce a value without a citation "
            "(enforced: aether.agents.review.freeze_terms refuses uncited fields)",
            "Bypass human review "
            "(enforced: freeze_terms raises ReviewRequired while any field pends)",
            "Alter a frozen agreement "
            "(enforced: CSATerms is a frozen dataclass; versions are additive)",
            "Follow instructions found inside a document "
            "(mitigated: aether.governance.sanitise frames content as data)",
        ),
        evaluation_status=EvaluationStatus.PASSED,
        deployment_status=DeploymentStatus.DEPLOYED,
        created_at="2026-08-14T00:00:00Z",
        updated_at="2026-08-22T00:00:00Z",
        change_note=(
            "Initial registration. Evaluated against hand-authored ground truth in "
            "fixtures/ground_truth/ by aether.agents.evaluation. In replay mode the "
            "cached extraction is itself hand-authored, so that score demonstrates "
            "the harness rather than model accuracy."
        ),
    ),
    ModelCard(
        model_id="claude-opus-5",
        provider="anthropic",
        model_version="claude-opus-5",
        prompt_version="guide/v1",
        policy_version="aether-ai-policy/v1",
        approved_use_case=UseCase.DESK_ASSISTANCE,
        capabilities=(
            "Route a desk user's question to deterministic tools",
            "Explain what a screen shows and what to do next",
            "Compose prose between tool results",
        ),
        prohibited_actions=(
            "State a figure no tool returned "
            "(enforced: aether.agents.guide.stray_figures discards the answer)",
            "Perform arithmetic "
            "(enforced: no tool computes; deltas come from the comparison endpoint)",
            "Answer past a permission refusal "
            "(enforced: tools return NOT_PERMITTED before the model sees data)",
            "Approve, freeze or execute anything (enforced: no such tool is registered)",
        ),
        evaluation_status=EvaluationStatus.PASSED,
        deployment_status=DeploymentStatus.DEPLOYED,
        created_at="2026-08-21T00:00:00Z",
        updated_at="2026-08-22T00:00:00Z",
        change_note="Initial registration of the desk assistant.",
    ),
)


def cards(use_case: UseCase | None = None) -> tuple[ModelCard, ...]:
    """Every registered card, optionally filtered by use case."""
    if use_case is None:
        return REGISTRY
    return tuple(card for card in REGISTRY if card.approved_use_case is use_case)


def resolve(use_case: UseCase, registry: tuple[ModelCard, ...] = REGISTRY) -> ModelCard:
    """The card cleared to serve this use case.

    Raises :class:`ModelNotDeployedError` rather than returning ``None``: a caller that
    forgot to check would otherwise proceed with an unregistered model, which is
    the exact failure this registry exists to prevent.
    """
    candidates = [
        card for card in registry if card.approved_use_case is use_case and card.is_servable
    ]
    if not candidates:
        registered = [c for c in registry if c.approved_use_case is use_case]
        if not registered:
            raise ModelNotDeployedError(use_case, f"No model is registered for {use_case.value}.")
        states = ", ".join(
            f"{c.key} is {c.deployment_status.value}/{c.evaluation_status.value}"
            for c in registered
        )
        raise ModelNotDeployedError(
            use_case,
            f"No model is cleared to serve {use_case.value}. Registered: {states}.",
        )
    if len(candidates) > 1:
        keys = ", ".join(c.key for c in candidates)
        raise ModelNotDeployedError(
            use_case,
            f"{len(candidates)} models are simultaneously deployed for "
            f"{use_case.value} ({keys}). Exactly one must serve a use case, so that "
            "an output can be attributed without ambiguity.",
        )
    return candidates[0]


def attribute(card: ModelCard, mode: str) -> Attribution:
    """Stamp an output with the model that produced it."""
    return Attribution(
        model_id=card.model_id,
        provider=card.provider,
        model_version=card.model_version,
        prompt_version=card.prompt_version,
        policy_version=card.policy_version,
        use_case=card.approved_use_case,
        mode=mode,
        registry_key=card.key,
    )


def promote(
    card: ModelCard,
    to: DeploymentStatus,
    approver: str,
    occurred_at: str,
    note: str = "",
) -> ModelCard:
    """Advance a card one step along the promotion path.

    Refuses a skipped step and refuses an unnamed approver. It does not verify
    that the evaluation or the security tests actually passed — a human asserts
    that by promoting, and the assertion is recorded with their name against it.

    Returns a new card; the original is unchanged, because a promotion is a new
    version of the record rather than an edit to the old one.
    """
    if not approver.strip():
        raise ValueError("A promotion must name the person who approved it.")

    if to is DeploymentStatus.RETIRED:
        return replace(
            card,
            deployment_status=to,
            updated_at=occurred_at,
            change_note=f"Retired by {approver}. {note}".strip(),
        )

    try:
        current = PROMOTION_PATH.index(card.deployment_status)
    except ValueError as exc:
        raise ValueError(
            f"{card.key} is {card.deployment_status.value}, which is not on the "
            "promotion path. A retired model is re-registered, not promoted."
        ) from exc

    try:
        target = PROMOTION_PATH.index(to)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{to} is not a promotion state.") from exc

    if target != current + 1:
        expected = PROMOTION_PATH[current + 1] if current + 1 < len(PROMOTION_PATH) else None
        raise ValueError(
            f"{card.key} is {card.deployment_status.value}; the next step is "
            f"{expected.value if expected else 'none — already deployed'}, not {to.value}. "
            "Steps are not skipped: each one is a gate somebody signed for."
        )

    return replace(
        card,
        deployment_status=to,
        updated_at=occurred_at,
        change_note=f"Promoted to {to.value} by {approver}. {note}".strip(),
    )
