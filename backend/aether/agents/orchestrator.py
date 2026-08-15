"""The agent swarm — Legal-Clause, Risk-Engine, Collateral-Optimizer.

Three agents, each owning one stage, handing typed results to the next::

    Legal-Clause Agent          reads the Annex, cites, flags, hands over CSATerms
            |
            v  frozen, reviewed terms
    Risk-Engine Agent           routes deterministic valuation and margin tools
            |
            v  exposure, sensitivities, credit support amount
    Collateral-Optimizer Agent  routes optimisation and settlement tools
            |
            v  allocation, settlement instruction
    Decision

.. rubric:: The rule this module exists to enforce

An agent chooses **which tool to call and with what references**. The tool computes.
That separation is not a convention here — it is enforced by the type of a tool
call's arguments:

.. code-block:: python

    Argument = str | int | bool | None

A :class:`ToolCall` whose arguments contain a ``float``, a ``Decimal`` or a
:class:`~aether.core.money.Money` is rejected at construction. An agent therefore
**cannot** pass a number that becomes a cash amount, even by accident, even if a
language model hallucinated one into the plan. Monetary values exist only inside
typed engine results, which flow between tools through the run context and never
through a plan.

.. rubric:: What this proves in the audit trail

Every tool call produces two chained events:

1. ``TOOL_CALLED`` — actor type ``AGENT``, payload carrying the tool, the intent and
   the arguments. It contains no monetary value, because it cannot.
2. the engine's own ``*_COMPUTED`` event — actor type ``ENGINE``, payload carrying
   the numbers.

A reader of the chain can therefore verify, event by event, that no figure
originated on the agent side. The claim is checkable rather than asserted.

.. rubric:: Planning

The routing policy is **deterministic and conditional**: the optimiser is only
invoked for a Delivery Amount, settlement only when an allocation exists, and an
infeasible allocation escalates instead of proceeding. That policy is the demo path
and is what makes the run reproducible.

In ``live`` mode the plan may instead be produced by the model, which selects tools
and reference arguments from the registry. The result is validated against the
registry before anything executes, and any plan naming an unknown tool, omitting a
required argument or carrying a numeric argument is rejected and the deterministic
policy is used instead. ``plan_source`` records which applied.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from aether.agents.schema import ExtractionResult
from aether.core.audit import ActorType, AuditChain
from aether.core.collateral import CollateralInventory
from aether.core.csa import CallDirection, MarginCallResult, compute_margin_call
from aether.core.csa_terms import CSATerms
from aether.core.exposure import ExposureResult, compute_exposure
from aether.core.im import InitialMarginResult, compute_schedule_im
from aether.core.instruments import Portfolio
from aether.core.market import MarketSnapshot
from aether.core.money import Money
from aether.core.optimize import OptimizationResult, OptimizerStatus, optimize_collateral
from aether.core.sensitivities import SensitivityMarginResult, compute_sensitivity_margin
from aether.core.settlement import SettlementInstruction, build_settlement_instruction

__all__ = [
    "TOOL_REGISTRY",
    "AgentRole",
    "PlanSource",
    "RunContext",
    "SwarmResult",
    "ToolCall",
    "ToolSpec",
    "legal_clause_stage",
    "run_swarm",
    "validate_plan",
]


class AgentRole(StrEnum):
    """The three agents of the swarm."""

    LEGAL_CLAUSE = "LEGAL_CLAUSE_AGENT"
    RISK_ENGINE = "RISK_ENGINE_AGENT"
    COLLATERAL_OPTIMIZER = "COLLATERAL_OPTIMIZER_AGENT"


class PlanSource(StrEnum):
    POLICY = "DETERMINISTIC_POLICY"
    MODEL = "MODEL_PLANNED"


#: The only argument types an agent may put in a tool call. Deliberately excludes
#: every numeric type that could become a cash amount.
Argument = str | int | bool | None

_FORBIDDEN_ARGUMENT_NOTE = (
    "Agents pass references, not values. A tool call may carry identifiers, counts "
    "and flags only. Monetary and rate values reach a tool from a previous engine "
    "result held in the run context, never from a plan — which is what makes "
    "'language models extract, deterministic engines compute' structurally true."
)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One agent's decision to invoke one deterministic tool."""

    agent: AgentRole
    tool: str
    intent: str
    arguments: Mapping[str, Argument] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in self.arguments.items():
            # bool is a subclass of int, so it is covered by the int branch.
            if not isinstance(value, str | int | type(None)):
                raise TypeError(
                    f"Tool call {self.tool!r} argument {name!r} is "
                    f"{type(value).__name__}, which is not permitted. "
                    f"{_FORBIDDEN_ARGUMENT_NOTE}"
                )
        object.__setattr__(self, "arguments", dict(self.arguments))

    @property
    def audit_payload(self) -> dict[str, Any]:
        return {
            "agent": self.agent.value,
            "tool": self.tool,
            "intent": self.intent,
            "arguments": dict(self.arguments),
            "carries_no_monetary_value": True,
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """What a tool needs and what it produces."""

    name: str
    owner: AgentRole
    description: str
    required_arguments: tuple[str, ...]
    produces: str


#: Every deterministic tool an agent may invoke. An agent cannot reach the engine
#: except through this table.
TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="price_netting_set",
        owner=AgentRole.RISK_ENGINE,
        description=(
            "Mark every trade in the netting set to the pinned snapshot and net "
            "within that set only."
        ),
        required_arguments=("netting_set_id", "snapshot_id"),
        produces="exposure",
    ),
    ToolSpec(
        name="measure_risk_sensitivities",
        owner=AgentRole.RISK_ENGINE,
        description=(
            "Bucketed delta sensitivities by full revaluation, risk-weighted and "
            "aggregated through correlation matrices."
        ),
        required_arguments=("netting_set_id", "snapshot_id"),
        produces="sensitivity_margin",
    ),
    ToolSpec(
        name="compute_schedule_initial_margin",
        owner=AgentRole.RISK_ENGINE,
        description="BCBS-IOSCO standardised schedule initial margin.",
        required_arguments=("netting_set_id", "snapshot_id"),
        produces="initial_margin",
    ),
    ToolSpec(
        name="compute_credit_support_amount",
        owner=AgentRole.RISK_ENGINE,
        description=(
            "CSA Paragraph 2/3 waterfall: Credit Support Amount, Threshold, "
            "Independent Amount, Minimum Transfer Amount gate and rounding."
        ),
        required_arguments=("agreement_id",),
        produces="margin_call",
    ),
    ToolSpec(
        name="optimise_collateral",
        owner=AgentRole.COLLATERAL_OPTIMIZER,
        description=(
            "Cheapest-to-deliver linear program over the eligible inventory, "
            "subject to coverage, eligibility and concentration constraints."
        ),
        required_arguments=("agreement_id", "inventory_id"),
        produces="allocation",
    ),
    ToolSpec(
        name="generate_settlement_instruction",
        owner=AgentRole.COLLATERAL_OPTIMIZER,
        description=(
            "ISO 20022-shaped margin call request and collateral proposal. "
            "Generated, never transmitted."
        ),
        required_arguments=("agreement_id",),
        produces="settlement",
    ),
)

_BY_NAME = {spec.name: spec for spec in TOOL_REGISTRY}


@dataclass(frozen=True, slots=True)
class RunContext:
    """Everything the tools may read. Pinned, and never mutated by an agent."""

    terms: CSATerms
    portfolio: Portfolio
    inventory: CollateralInventory
    snapshot: MarketSnapshot
    as_of: date
    posted_value: Money | None = None


@dataclass(slots=True)
class _Results:
    """Typed engine outputs, accumulated as tools execute."""

    exposure: ExposureResult | None = None
    sensitivity_margin: SensitivityMarginResult | None = None
    initial_margin: InitialMarginResult | None = None
    margin_call: MarginCallResult | None = None
    allocation: OptimizationResult | None = None
    settlement: SettlementInstruction | None = None


@dataclass(frozen=True, slots=True)
class AgentAction:
    """One executed tool call, as rendered for the UI and the audit trail."""

    agent: AgentRole
    tool: str
    intent: str
    arguments: Mapping[str, Argument]
    outcome: str


@dataclass(frozen=True, slots=True)
class SwarmResult:
    """What the swarm produced, plus the trace of how it decided."""

    exposure: ExposureResult
    sensitivity_margin: SensitivityMarginResult
    initial_margin: InitialMarginResult
    margin_call: MarginCallResult
    allocation: OptimizationResult | None
    settlement: SettlementInstruction | None
    actions: tuple[AgentAction, ...]
    plan_source: PlanSource
    chain: AuditChain


# ------------------------------------------------------ legal-clause stage


def legal_clause_stage(
    extraction: ExtractionResult,
    terms: CSATerms,
    chain: AuditChain,
    stamp: str,
) -> AuditChain:
    """Record the Legal-Clause Agent's stage in the audit chain.

    Four kinds of event, and the actor type of each is the point:

    ``DOCUMENT_INGESTED``   ``SYSTEM``  the content hash the whole run is anchored to
    ``TERMS_EXTRACTED``     ``AGENT``   what the model produced, and how sure it was
    ``FIELD_CONFIRMED``     ``HUMAN``   one per reviewer decision, with the rationale
    ``TERMS_FROZEN``        ``HUMAN``   the version the engine is permitted to compute on

    Without these the chain proves only that arithmetic happened. With them it proves
    where every contractual value came from and who accepted it — which is the claim
    the product is actually making.
    """
    chain = chain.append(
        actor="aether.agents.legal_clause",
        actor_type=ActorType.SYSTEM,
        action="DOCUMENT_INGESTED",
        entity_type="document",
        entity_id=extraction.document_id,
        occurred_at=stamp,
        payload={
            "document_sha256": extraction.document_sha256,
            "simulated": True,
        },
    )

    flagged = [f.path for f in extraction.fields if f.requires_review]
    chain = chain.append(
        actor=AgentRole.LEGAL_CLAUSE.value,
        actor_type=ActorType.AGENT,
        action="TERMS_EXTRACTED",
        entity_type="document",
        entity_id=extraction.document_id,
        occurred_at=stamp,
        payload={
            "agent": AgentRole.LEGAL_CLAUSE.value,
            "model_id": extraction.model_id,
            "prompt_version": extraction.prompt_version,
            "mode": extraction.mode,
            "temperature": str(extraction.temperature),
            "field_count": len(extraction.fields),
            "cited_field_count": len(extraction.fields) - len(extraction.uncited),
            "mean_confidence": str(extraction.mean_confidence),
            "flagged_for_review": flagged,
            "note": (
                "Typed, cited candidate values. No figure here has reached the "
                "margin engine at this point."
            ),
        },
    )

    for field_value in extraction.fields:
        if field_value.reviewer is None:
            continue
        chain = chain.append(
            actor=field_value.reviewer,
            actor_type=ActorType.HUMAN,
            action="FIELD_CONFIRMED",
            entity_type="field",
            entity_id=field_value.path,
            occurred_at=stamp,
            payload={
                "path": field_value.path,
                "reviewer": field_value.reviewer,
                "rationale": field_value.reviewer_rationale,
                "confidence_at_extraction": str(field_value.confidence),
                "review_reason": (
                    field_value.review_reason.value if field_value.review_reason else None
                ),
            },
        )

    return chain.append(
        actor="collateral.ops",
        actor_type=ActorType.HUMAN,
        action="TERMS_FROZEN",
        entity_type="agreement",
        entity_id=terms.agreement_id,
        occurred_at=stamp,
        payload={
            "agreement_id": terms.agreement_id,
            "terms_version": terms.terms_version,
            "netting_set_id": terms.netting_set_id,
            "document_sha256": extraction.document_sha256,
            "note": (
                "Every flagged field was resolved by a human before freezing. The "
                "engine computes only on this version."
            ),
        },
    )


# --------------------------------------------------------------- planning


def validate_plan(plan: tuple[ToolCall, ...]) -> tuple[bool, str]:
    """Check a plan against the registry before anything executes."""
    if not plan:
        return False, "Plan is empty."
    for call in plan:
        spec = _BY_NAME.get(call.tool)
        if spec is None:
            return False, f"Unknown tool {call.tool!r}. Available: {sorted(_BY_NAME)}."
        if spec.owner is not call.agent:
            return False, f"{call.tool!r} belongs to {spec.owner.value}, not {call.agent.value}."
        missing = [a for a in spec.required_arguments if a not in call.arguments]
        if missing:
            return False, f"{call.tool!r} is missing required argument(s): {missing}."
    return True, "Plan is valid."


def risk_engine_plan(context: RunContext) -> tuple[ToolCall, ...]:
    """The Risk-Engine Agent's routing decision.

    Valuation and the credit support waterfall are always required. Sensitivity
    measurement is skipped for an empty book, because there is nothing to perturb.
    """
    netting_set = context.terms.netting_set_id
    snapshot = context.snapshot.snapshot_id

    calls = [
        ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="price_netting_set",
            intent=(
                f"Value {len(context.portfolio)} trades against pinned snapshot "
                f"{snapshot} and net within {netting_set} only."
            ),
            arguments={"netting_set_id": netting_set, "snapshot_id": snapshot},
        )
    ]

    if len(context.portfolio) > 0:
        calls.append(
            ToolCall(
                agent=AgentRole.RISK_ENGINE,
                tool="measure_risk_sensitivities",
                intent=(
                    "Measure bucketed delta risk by revaluation and aggregate it "
                    "through the risk-weight and correlation framework."
                ),
                arguments={"netting_set_id": netting_set, "snapshot_id": snapshot},
            )
        )

    calls.append(
        ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="compute_schedule_initial_margin",
            intent="Compute the standardised schedule initial margin for comparison.",
            arguments={"netting_set_id": netting_set, "snapshot_id": snapshot},
        )
    )
    calls.append(
        ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="compute_credit_support_amount",
            intent=(
                "Apply the CSA waterfall: Threshold, Independent Amount, Minimum "
                "Transfer Amount gate and directional rounding."
            ),
            arguments={"agreement_id": context.terms.agreement_id},
        )
    )
    return tuple(calls)


def collateral_optimizer_plan(
    context: RunContext, margin_call: MarginCallResult
) -> tuple[ToolCall, ...]:
    """The Collateral-Optimizer Agent's routing decision.

    Genuinely conditional, on three separate grounds:

    - **No transfer** means no allocation and no instruction.
    - A **Return Amount** hands collateral back from the balance already held, so
      there is nothing to select.
    - A Delivery Amount owed **by the counterparty** is not ours to collateralise.
      Optimising our own inventory against someone else's obligation would be
      nonsense; the correct output is a margin call request to them, and their
      collateral proposal comes back in reply.

    Only a Delivery Amount that *we* owe reaches the linear program.
    """
    if not margin_call.has_call:
        return ()

    if margin_call.direction is not CallDirection.DELIVERY:
        return (
            ToolCall(
                agent=AgentRole.COLLATERAL_OPTIMIZER,
                tool="generate_settlement_instruction",
                intent=(
                    "Return Amount: collateral is released from the balance already "
                    "held, so no allocation is selected — instruct the release."
                ),
                arguments={"agreement_id": context.terms.agreement_id},
            ),
        )

    if margin_call.transferor.value != context.inventory.owner:
        return (
            ToolCall(
                agent=AgentRole.COLLATERAL_OPTIMIZER,
                tool="generate_settlement_instruction",
                intent=(
                    f"{margin_call.transferor.value} owes the collateral, not "
                    f"{context.inventory.owner}. Our inventory is not the source, so "
                    f"no allocation is optimised — issue the margin call request and "
                    f"await their collateral proposal."
                ),
                arguments={
                    "agreement_id": context.terms.agreement_id,
                    "transferor": margin_call.transferor.value,
                },
            ),
        )

    return (
        ToolCall(
            agent=AgentRole.COLLATERAL_OPTIMIZER,
            tool="optimise_collateral",
            intent=(
                "Select the cheapest eligible allocation covering the Delivery "
                "Amount, ranked by cost per effective unit."
            ),
            arguments={
                "agreement_id": context.terms.agreement_id,
                "inventory_id": context.inventory.inventory_id,
            },
        ),
        ToolCall(
            agent=AgentRole.COLLATERAL_OPTIMIZER,
            tool="generate_settlement_instruction",
            intent="Render the approved allocation as a collateral settlement instruction.",
            arguments={"agreement_id": context.terms.agreement_id},
        ),
    )


# -------------------------------------------------------------- execution


def _execute(call: ToolCall, context: RunContext, results: _Results) -> str:
    """Run one tool and record its output on ``results``. Returns a short outcome."""
    match call.tool:
        case "price_netting_set":
            results.exposure = compute_exposure(
                context.portfolio,
                context.snapshot,
                context.as_of,
                context.terms.base_currency,
                netting_set_id=context.terms.netting_set_id,
            )
            trades = len(context.portfolio)
            return f"Net exposure {results.exposure.exposure} across {trades} trades."

        case "measure_risk_sensitivities":
            results.sensitivity_margin = compute_sensitivity_margin(
                context.portfolio,
                context.snapshot,
                context.as_of,
                context.terms.base_currency,
                netting_set_id=context.terms.netting_set_id,
            )
            count = len(results.sensitivity_margin.sensitivities)
            margin = results.sensitivity_margin.total_margin
            return f"{count} bucketed sensitivities, margin {margin}."

        case "compute_schedule_initial_margin":
            if results.exposure is None:
                raise RuntimeError("compute_schedule_initial_margin requires exposure first.")
            results.initial_margin = compute_schedule_im(
                context.portfolio,
                results.exposure,
                context.snapshot,
                context.terms.base_currency,
            )
            return f"Schedule IM {results.initial_margin.initial_margin}."

        case "compute_credit_support_amount":
            if results.exposure is None:
                raise RuntimeError("compute_credit_support_amount requires exposure first.")
            results.margin_call = compute_margin_call(
                context.terms, results.exposure, posted_value=context.posted_value
            )
            return results.margin_call.summary

        case "optimise_collateral":
            if results.margin_call is None:
                raise RuntimeError("optimise_collateral requires a margin call first.")
            results.allocation = optimize_collateral(
                context.terms,
                context.inventory,
                context.snapshot,
                results.margin_call.call_amount,
            )
            if results.allocation.status is OptimizerStatus.OPTIMAL:
                return (
                    f"{len(results.allocation.lines)} assets at "
                    f"{results.allocation.total_cost} per annum, "
                    f"{results.allocation.saving_percentage}% below cash-first."
                )
            return results.allocation.message

        case "generate_settlement_instruction":
            if results.margin_call is None:
                raise RuntimeError("generate_settlement_instruction requires a margin call.")
            results.settlement = build_settlement_instruction(
                context.terms, results.margin_call, results.allocation
            )
            if results.settlement is None:
                return "No transfer is due, so no instruction was generated."
            return (
                f"{results.settlement.instruction_id} generated, "
                f"{len(results.settlement.legs)} legs, awaiting approval."
            )

        case _:  # pragma: no cover - validate_plan rejects unknown tools first
            raise KeyError(f"No such tool: {call.tool}")


def _engine_event(
    chain: AuditChain, call: ToolCall, context: RunContext, results: _Results, stamp: str
) -> AuditChain:
    """Append the ENGINE event carrying the numbers the tool produced."""
    match call.tool:
        case "price_netting_set":
            exposure = results.exposure
            assert exposure is not None
            return chain.append(
                actor="aether.core.exposure",
                actor_type=ActorType.ENGINE,
                action="EXPOSURE_COMPUTED",
                entity_type="netting_set",
                entity_id=exposure.netting_set_id,
                occurred_at=stamp,
                payload={
                    "exposure": exposure.exposure,
                    "gross_positive": exposure.gross_positive,
                    "netting_benefit": exposure.netting_benefit,
                    "trade_count": exposure.trade_count,
                    "snapshot_id": exposure.snapshot_id,
                },
            )

        case "measure_risk_sensitivities":
            risk = results.sensitivity_margin
            assert risk is not None
            return chain.append(
                actor="aether.core.sensitivities",
                actor_type=ActorType.ENGINE,
                action="RISK_SENSITIVITIES_MEASURED",
                entity_type="netting_set",
                entity_id=risk.netting_set_id,
                occurred_at=stamp,
                payload={
                    "method": risk.method,
                    "sensitivity_count": len(risk.sensitivities),
                    "interest_rate_margin": risk.interest_rate_margin,
                    "fx_margin": risk.fx_margin,
                    "vega_margin": risk.vega_margin,
                    "total_margin": risk.total_margin,
                    "note": risk.disclaimer,
                },
            )

        case "compute_schedule_initial_margin":
            im = results.initial_margin
            assert im is not None
            return chain.append(
                actor="aether.core.im",
                actor_type=ActorType.ENGINE,
                action="INITIAL_MARGIN_COMPUTED",
                entity_type="netting_set",
                entity_id=im.netting_set_id,
                occurred_at=stamp,
                payload={
                    "method": im.method,
                    "gross_im": im.gross_im,
                    "net_to_gross_ratio": im.net_to_gross_ratio,
                    "initial_margin": im.initial_margin,
                    "note": "Indicative. Not added to the variation margin call.",
                },
            )

        case "compute_credit_support_amount":
            call_result = results.margin_call
            assert call_result is not None
            return chain.append(
                actor="aether.core.csa",
                actor_type=ActorType.ENGINE,
                action="MARGIN_CALL_COMPUTED",
                entity_type="agreement",
                entity_id=context.terms.agreement_id,
                occurred_at=stamp,
                payload={
                    "transferor": call_result.transferor,
                    "threshold": call_result.threshold,
                    "independent_amount": call_result.independent_amount,
                    "credit_support_amount": call_result.credit_support_amount,
                    "posted_value": call_result.posted_value,
                    "unrounded_amount": call_result.unrounded_amount,
                    "call_amount": call_result.call_amount,
                    "direction": call_result.direction,
                    "gated_by_mta": call_result.gated_by_mta,
                    "mta_before_rounding": call_result.mta_before_rounding,
                    "engine_version": call_result.engine_version,
                    "trace": [
                        {"label": s.label, "value": s.value, "clause": s.clause}
                        for s in call_result.trace
                    ],
                },
            )

        case "optimise_collateral":
            allocation = results.allocation
            assert allocation is not None
            return chain.append(
                actor="aether.core.optimize",
                actor_type=ActorType.ENGINE,
                action="COLLATERAL_OPTIMISED",
                entity_type="agreement",
                entity_id=context.terms.agreement_id,
                occurred_at=stamp,
                payload={
                    "status": allocation.status,
                    "required_value": allocation.required_value,
                    "allocated_value": allocation.allocated_value,
                    "total_cost": allocation.total_cost,
                    "baseline_cost": allocation.baseline_cost,
                    "baseline_covers_requirement": allocation.baseline_covers,
                    "saving": allocation.saving,
                    "lines": [
                        {
                            "asset_id": line.asset_id,
                            "market_value_posted": line.market_value_posted,
                            "effective_value": line.effective_value,
                            "effective_percentage": line.effective_percentage,
                            "cost_per_effective_unit_bps": line.cost_per_effective_unit_bps,
                        }
                        for line in allocation.lines
                    ],
                    "binding_constraints": [
                        {"name": c.name, "shadow_price_bps": c.shadow_price_bps}
                        for c in allocation.binding_constraints
                    ],
                    "excluded": [{"asset_id": a, "reason": r} for a, r in allocation.excluded],
                },
            )

        case "generate_settlement_instruction":
            instruction = results.settlement
            if instruction is None:
                return chain
            return chain.append(
                actor="aether.core.settlement",
                actor_type=ActorType.ENGINE,
                action="SETTLEMENT_INSTRUCTION_GENERATED",
                entity_type="settlement_instruction",
                entity_id=instruction.instruction_id,
                occurred_at=stamp,
                payload={
                    "message_types": list(instruction.message_types),
                    "value_date": instruction.value_date,
                    "deliverer": instruction.deliverer,
                    "receiver": instruction.receiver,
                    "call_amount": instruction.call_amount,
                    "collateral_value": instruction.collateral_value,
                    "leg_count": len(instruction.legs),
                    "status": instruction.status,
                    "transmitted": False,
                    "note": instruction.disclaimer,
                },
            )

        case _:  # pragma: no cover
            return chain


def _run_stage(
    plan: tuple[ToolCall, ...],
    context: RunContext,
    results: _Results,
    chain: AuditChain,
    *,
    stamp: str,
    actions: list[AgentAction],
) -> AuditChain:
    """Execute one agent's plan, chaining an AGENT event before every ENGINE event."""
    for call in plan:
        chain = chain.append(
            actor=call.agent.value,
            actor_type=ActorType.AGENT,
            action="TOOL_CALLED",
            entity_type="tool",
            entity_id=call.tool,
            occurred_at=stamp,
            payload=call.audit_payload,
        )
        outcome = _execute(call, context, results)
        chain = _engine_event(chain, call, context, results, stamp)
        actions.append(
            AgentAction(
                agent=call.agent,
                tool=call.tool,
                intent=call.intent,
                arguments=dict(call.arguments),
                outcome=outcome,
            )
        )
    return chain


def run_swarm(
    context: RunContext,
    chain: AuditChain,
    stamp: str,
    plan_source: PlanSource = PlanSource.POLICY,
    risk_plan: tuple[ToolCall, ...] | None = None,
) -> SwarmResult:
    """Run the Risk-Engine and Collateral-Optimizer agents over a pinned context.

    The Legal-Clause Agent runs earlier and upstream: its output is
    ``context.terms``, which by construction can only have been produced by
    :func:`aether.agents.review.freeze_terms` after every flagged field was resolved.
    """
    results = _Results()
    actions: list[AgentAction] = []

    plan = risk_plan if risk_plan is not None else risk_engine_plan(context)
    valid, message = validate_plan(plan)
    if not valid:
        raise ValueError(f"Rejected Risk-Engine plan: {message}")
    chain = _run_stage(plan, context, results, chain, stamp=stamp, actions=actions)

    assert results.exposure is not None
    assert results.initial_margin is not None
    assert results.margin_call is not None

    optimizer_plan = collateral_optimizer_plan(context, results.margin_call)
    if optimizer_plan:
        valid, message = validate_plan(optimizer_plan)
        if not valid:  # pragma: no cover - the policy cannot emit an invalid plan
            raise ValueError(f"Rejected Collateral-Optimizer plan: {message}")
        chain = _run_stage(optimizer_plan, context, results, chain, stamp=stamp, actions=actions)
    else:
        actions.append(
            AgentAction(
                agent=AgentRole.COLLATERAL_OPTIMIZER,
                tool="(no tool invoked)",
                intent="Decide whether any collateral needs to be selected.",
                arguments={},
                outcome=(
                    "No transfer is due, so no allocation was attempted and no "
                    "settlement instruction was generated."
                ),
            )
        )
        chain = chain.append(
            actor=AgentRole.COLLATERAL_OPTIMIZER.value,
            actor_type=ActorType.AGENT,
            action="NO_TOOL_REQUIRED",
            entity_type="agreement",
            entity_id=context.terms.agreement_id,
            occurred_at=stamp,
            payload={
                "agent": AgentRole.COLLATERAL_OPTIMIZER.value,
                "reason": "No transfer is due under the agreement.",
            },
        )

    if results.sensitivity_margin is None:  # pragma: no cover - only for an empty book
        results.sensitivity_margin = compute_sensitivity_margin(
            context.portfolio,
            context.snapshot,
            context.as_of,
            context.terms.base_currency,
            netting_set_id=context.terms.netting_set_id,
        )

    return SwarmResult(
        exposure=results.exposure,
        sensitivity_margin=results.sensitivity_margin,
        initial_margin=results.initial_margin,
        margin_call=results.margin_call,
        allocation=results.allocation,
        settlement=results.settlement,
        actions=tuple(actions),
        plan_source=plan_source,
        chain=chain,
    )


# ------------------------------------------------------------ model plans


def parse_model_plan(raw: str) -> tuple[ToolCall, ...]:
    """Parse a model-produced plan into typed tool calls.

    Every guard here is load-bearing. A model that emits a monetary argument, an
    unknown tool or a malformed structure produces a :class:`ValueError`, the plan is
    discarded, and the caller falls back to the deterministic policy — so a bad plan
    degrades the *narration*, never the arithmetic.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Plan was not valid JSON: {exc}") from exc

    entries = payload.get("plan") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("Plan must be a list of tool calls.")

    calls: list[ToolCall] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each plan entry must be an object.")
        tool = str(entry.get("tool", ""))
        spec = _BY_NAME.get(tool)
        if spec is None:
            raise ValueError(f"Unknown tool {tool!r}.")
        arguments = entry.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError(f"{tool!r}: arguments must be an object.")
        # ToolCall.__post_init__ rejects any numeric or monetary argument.
        calls.append(
            ToolCall(
                agent=spec.owner,
                tool=tool,
                intent=str(entry.get("intent", "")),
                arguments=arguments,
            )
        )

    valid, message = validate_plan(tuple(calls))
    if not valid:
        raise ValueError(message)
    return tuple(calls)
