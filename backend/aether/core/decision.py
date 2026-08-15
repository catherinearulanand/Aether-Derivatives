"""The decision record — the terminal state of the pipeline.

Every run ends in exactly one Decision, which is the thing a collateral operations
team would actually act on. It carries the recommendation, the figures behind it, and
the audit chain head hash that makes the whole run verifiable.

.. rubric:: On autonomy

The pipeline produces a **proposal**. `DecisionStatus.PENDING_APPROVAL` is the
terminal state of an automated run: no collateral moves until a human approves, and
the system never executes a real financial transaction. A settlement instruction is
generated in message shape by :mod:`aether.core.settlement` and is never transmitted;
that boundary is stated on every surface that renders one.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from aether.core.csa import CallDirection, MarginCallResult
from aether.core.csa_terms import Party
from aether.core.money import Currency, Money
from aether.core.optimize import OptimizationResult, OptimizerStatus

__all__ = ["Decision", "DecisionAction", "DecisionStatus", "build_decision"]


class DecisionAction(StrEnum):
    POST_COLLATERAL = "POST_COLLATERAL"
    RECALL_COLLATERAL = "RECALL_COLLATERAL"
    #: The counterparty owes us. We issue a call and they choose what to deliver —
    #: optimising our own inventory against their obligation would be meaningless.
    DEMAND_COLLATERAL = "DEMAND_COLLATERAL"
    NO_ACTION = "NO_ACTION"
    ESCALATE = "ESCALATE"


class DecisionStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Decision:
    """What the pipeline recommends, and the evidence for it."""

    decision_id: str
    agreement_id: str
    netting_set_id: str
    snapshot_id: str
    as_of: date
    engine_version: str

    action: DecisionAction
    status: DecisionStatus
    transferor: Party
    amount: Money
    currency: Currency

    exposure: Money
    credit_support_amount: Money
    initial_margin: Money

    allocation_cost: Money
    baseline_cost: Money
    saving: Money
    saving_percentage: Decimal
    asset_count: int

    headline: str
    rationale: tuple[str, ...]
    requires_human_approval: bool = True
    simulated: bool = True

    @property
    def disclaimer(self) -> str:
        return (
            "Proposal only. No financial transaction is executed. A settlement "
            "instruction is generated in ISO 20022 message shape and is never "
            "transmitted: no network connectivity exists. All market data is simulated."
        )


def build_decision(
    decision_id: str,
    margin_call: MarginCallResult,
    allocation: OptimizationResult | None,
    collateral_owner: Party | None = None,
) -> Decision:
    """Assemble the decision from a margin call and, where relevant, an allocation.

    ``collateral_owner`` is the party whose inventory the optimizer may draw on. When
    the Transferor is somebody else, the absence of an allocation is not a failure —
    it is the correct outcome, and the decision is to call for collateral rather than
    to post it.
    """
    base = margin_call.base_currency
    zero = Money.zero(base)

    if not margin_call.has_call:
        reason = (
            "the amount due is below the Minimum Transfer Amount"
            if margin_call.gated_by_mta
            else "exposure sits within the Threshold"
        )
        return Decision(
            decision_id=decision_id,
            agreement_id=margin_call.agreement_id,
            netting_set_id=margin_call.netting_set_id,
            snapshot_id=margin_call.snapshot_id,
            as_of=margin_call.as_of,
            engine_version=margin_call.engine_version,
            action=DecisionAction.NO_ACTION,
            status=DecisionStatus.NO_ACTION_REQUIRED,
            transferor=margin_call.transferor,
            amount=zero,
            currency=base,
            exposure=margin_call.exposure,
            credit_support_amount=margin_call.credit_support_amount,
            initial_margin=margin_call.initial_margin,
            allocation_cost=zero,
            baseline_cost=zero,
            saving=zero,
            saving_percentage=Decimal(0),
            asset_count=0,
            headline="No collateral movement required.",
            rationale=(
                f"Net exposure of {margin_call.exposure} produces a Credit Support "
                f"Amount of {margin_call.credit_support_amount}.",
                f"No transfer is due because {reason}.",
            ),
            requires_human_approval=False,
        )

    if margin_call.direction is CallDirection.RETURN:
        return Decision(
            decision_id=decision_id,
            agreement_id=margin_call.agreement_id,
            netting_set_id=margin_call.netting_set_id,
            snapshot_id=margin_call.snapshot_id,
            as_of=margin_call.as_of,
            engine_version=margin_call.engine_version,
            action=DecisionAction.RECALL_COLLATERAL,
            status=DecisionStatus.PENDING_APPROVAL,
            transferor=margin_call.transferor,
            amount=margin_call.call_amount,
            currency=base,
            exposure=margin_call.exposure,
            credit_support_amount=margin_call.credit_support_amount,
            initial_margin=margin_call.initial_margin,
            allocation_cost=zero,
            baseline_cost=zero,
            saving=zero,
            saving_percentage=Decimal(0),
            asset_count=0,
            headline=f"Recall {margin_call.call_amount} of excess collateral.",
            rationale=(
                f"Collateral held ({margin_call.posted_value}) exceeds the Credit "
                f"Support Amount ({margin_call.credit_support_amount}).",
                f"Return Amount rounded down to {margin_call.call_amount} per the "
                f"agreement's rounding provision.",
            ),
        )

    # Delivery owed by the counterparty: we call, they propose. No allocation of ours
    # is involved, and treating its absence as a failure would be wrong.
    if (
        allocation is None
        and collateral_owner is not None
        and margin_call.transferor is not collateral_owner
    ):
        return Decision(
            decision_id=decision_id,
            agreement_id=margin_call.agreement_id,
            netting_set_id=margin_call.netting_set_id,
            snapshot_id=margin_call.snapshot_id,
            as_of=margin_call.as_of,
            engine_version=margin_call.engine_version,
            action=DecisionAction.DEMAND_COLLATERAL,
            status=DecisionStatus.PENDING_APPROVAL,
            transferor=margin_call.transferor,
            amount=margin_call.call_amount,
            currency=base,
            exposure=margin_call.exposure,
            credit_support_amount=margin_call.credit_support_amount,
            initial_margin=margin_call.initial_margin,
            allocation_cost=zero,
            baseline_cost=zero,
            saving=zero,
            saving_percentage=Decimal(0),
            asset_count=0,
            headline=(
                f"Call {margin_call.call_amount} of collateral from {margin_call.transferor.value}."
            ),
            rationale=(
                f"Net exposure of {margin_call.exposure} is in our favour, so "
                f"{margin_call.transferor.value} is the Transferor and its Threshold "
                f"of {margin_call.threshold} and Independent Amount of "
                f"{margin_call.independent_amount} govern this call.",
                f"Credit Support Amount {margin_call.credit_support_amount}, "
                f"Delivery Amount {margin_call.call_amount} after the Minimum "
                f"Transfer Amount test and rounding.",
                "No allocation is optimised: the collateral is owed by the "
                "counterparty, which selects what to deliver. A margin call request "
                "is generated and their collateral proposal is awaited.",
            ),
        )

    # Delivery by us. An allocation is required for the decision to be actionable.
    if allocation is None or allocation.status is OptimizerStatus.INFEASIBLE:
        message = allocation.message if allocation is not None else "No allocation was attempted."
        return Decision(
            decision_id=decision_id,
            agreement_id=margin_call.agreement_id,
            netting_set_id=margin_call.netting_set_id,
            snapshot_id=margin_call.snapshot_id,
            as_of=margin_call.as_of,
            engine_version=margin_call.engine_version,
            action=DecisionAction.ESCALATE,
            status=DecisionStatus.BLOCKED,
            transferor=margin_call.transferor,
            amount=margin_call.call_amount,
            currency=base,
            exposure=margin_call.exposure,
            credit_support_amount=margin_call.credit_support_amount,
            initial_margin=margin_call.initial_margin,
            allocation_cost=zero,
            baseline_cost=zero,
            saving=zero,
            saving_percentage=Decimal(0),
            asset_count=0,
            headline=(
                f"{margin_call.call_amount} is due but cannot be collateralised. "
                f"Escalate to the collateral desk."
            ),
            rationale=(
                f"A Delivery Amount of {margin_call.call_amount} is due from "
                f"{margin_call.transferor.value}.",
                message,
            ),
        )

    rationale = [
        f"Net exposure of {margin_call.exposure} against a Threshold of "
        f"{margin_call.threshold} produces a Credit Support Amount of "
        f"{margin_call.credit_support_amount}.",
        f"Delivery Amount of {margin_call.call_amount} after the Minimum Transfer "
        f"Amount test and rounding.",
        f"Cheapest eligible allocation uses {len(allocation.lines)} assets at "
        f"{allocation.total_cost} per annum, against {allocation.baseline_cost} for a "
        f"cash-first allocation, a saving of {allocation.saving} "
        f"({allocation.saving_percentage}%).",
    ]
    for constraint in allocation.binding_constraints:
        if constraint.name != "coverage":
            rationale.append(
                f"Binding constraint: {constraint.description}, costing "
                f"{constraint.shadow_price_bps}bp at the margin."
            )
    for asset_id, reason in allocation.excluded:
        rationale.append(f"Excluded {asset_id}: {reason}")

    return Decision(
        decision_id=decision_id,
        agreement_id=margin_call.agreement_id,
        netting_set_id=margin_call.netting_set_id,
        snapshot_id=margin_call.snapshot_id,
        as_of=margin_call.as_of,
        engine_version=margin_call.engine_version,
        action=DecisionAction.POST_COLLATERAL,
        status=DecisionStatus.PENDING_APPROVAL,
        transferor=margin_call.transferor,
        amount=margin_call.call_amount,
        currency=base,
        exposure=margin_call.exposure,
        credit_support_amount=margin_call.credit_support_amount,
        initial_margin=margin_call.initial_margin,
        allocation_cost=allocation.total_cost,
        baseline_cost=allocation.baseline_cost,
        saving=allocation.saving,
        saving_percentage=allocation.saving_percentage,
        asset_count=len(allocation.lines),
        headline=(
            f"{margin_call.transferor.value} to post {margin_call.call_amount} "
            f"across {len(allocation.lines)} assets."
        ),
        rationale=tuple(rationale),
    )
