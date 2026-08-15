"""The AETHER pipeline.

Wires the agent swarm and the deterministic engines end to end::

    document -> Legal-Clause Agent -> reviewed, frozen CSA terms
             -> Risk-Engine Agent          -> exposure (F5)
                                           -> risk-weighted sensitivities (F13)
                                           -> schedule initial margin (F7)
                                           -> credit support amount (F6)
             -> Collateral-Optimizer Agent -> collateral optimisation (F9)
                                           -> settlement instruction (F10)
             -> decision
             -> hash-chained audit trail (F12)

This module orchestrates and loads fixtures, so it lives **outside**
``aether.core``. Every calculation it reaches is pure, and every audit timestamp is
supplied from the pinned ``as_of`` rather than a system clock — which is what makes
:func:`run_pipeline` reproducible to the byte.

.. rubric:: Initial margin is reported, not charged

Both initial margin figures — the standardised schedule and the risk-weighted
sensitivity aggregation — are surfaced alongside the variation margin call and
**neither is added** to the VM Credit Support Amount. Under the market-standard
split, VM and IM sit under different agreements with different mechanics; folding an
IM figure into a VM call would overstate the requirement. They are shown as
indicative and labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aether.agents.orchestrator import (
    AgentAction,
    PlanSource,
    RunContext,
    run_swarm,
)
from aether.core.audit import ActorType, AuditChain
from aether.core.collateral import CollateralInventory
from aether.core.csa import MarginCallResult
from aether.core.csa_terms import CSATerms, Party
from aether.core.decision import Decision, build_decision
from aether.core.exposure import ExposureResult
from aether.core.im import InitialMarginResult
from aether.core.instruments import Portfolio
from aether.core.market import MarketSnapshot
from aether.core.money import Money
from aether.core.optimize import OptimizationResult
from aether.core.sensitivities import SensitivityMarginResult
from aether.core.settlement import SettlementInstruction
from aether.fixtures.loader import (
    load_agreement,
    load_inventory,
    load_portfolio,
    load_snapshot,
)

__all__ = ["PipelineResult", "run_pipeline", "run_scenario"]


def _owner_party(owner: str) -> Party | None:
    """Which party the collateral inventory belongs to, if it names one."""
    try:
        return Party(owner)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Everything one run produced, including its verifiable audit chain."""

    run_id: str
    terms: CSATerms
    snapshot: MarketSnapshot
    exposure: ExposureResult
    sensitivity_margin: SensitivityMarginResult
    initial_margin: InitialMarginResult
    margin_call: MarginCallResult
    allocation: OptimizationResult | None
    settlement: SettlementInstruction | None
    decision: Decision
    audit: AuditChain
    agent_actions: tuple[AgentAction, ...] = ()
    plan_source: PlanSource = PlanSource.POLICY

    @property
    def audit_verified(self) -> bool:
        valid, _, _ = self.audit.verify()
        return valid


def run_pipeline(
    terms: CSATerms,
    portfolio: Portfolio,
    inventory: CollateralInventory,
    snapshot: MarketSnapshot,
    as_of: date,
    *,
    run_id: str = "RUN-0001",
    actor: str = "aether.engine",
    posted_value: Money | None = None,
    chain: AuditChain | None = None,
) -> PipelineResult:
    """Execute the full deterministic slice and return every intermediate result.

    Identical inputs produce an identical result, including identical audit hashes.
    That is asserted by the determinism test rather than assumed.

    ``posted_value`` is the Value of the Credit Support Balance already held. It is a
    **parameter of the run**, not an adjustment applied afterwards: the audit chain
    must describe the run it is returned with, so there is exactly one place a margin
    call is computed and exactly one chain covering it.

    ``chain`` continues an existing audit chain — the API passes the chain that
    already records document ingestion, extraction and reviewer confirmation, so one
    unbroken hash chain spans the contract through to the decision.
    """
    # Audit timestamps come from the pinned valuation date. No clock is read, so two
    # runs of the same inputs hash identically.
    stamp = as_of.isoformat()
    chain = chain if chain is not None else AuditChain(chain_id=run_id)

    chain = chain.append(
        actor=actor,
        actor_type=ActorType.SYSTEM,
        action="RUN_STARTED",
        entity_type="run",
        entity_id=run_id,
        occurred_at=stamp,
        payload={
            "agreement_id": terms.agreement_id,
            "terms_version": terms.terms_version,
            "portfolio_id": portfolio.portfolio_id,
            "inventory_id": inventory.inventory_id,
            "snapshot_id": snapshot.snapshot_id,
            "as_of": as_of,
            "simulated": True,
        },
    )

    context = RunContext(
        terms=terms,
        portfolio=portfolio,
        inventory=inventory,
        snapshot=snapshot,
        as_of=as_of,
        posted_value=posted_value,
    )
    swarm = run_swarm(context, chain, stamp)
    chain = swarm.chain

    decision = build_decision(
        f"{run_id}-DEC",
        swarm.margin_call,
        swarm.allocation,
        collateral_owner=_owner_party(inventory.owner),
    )
    chain = chain.append(
        actor="aether.core.decision",
        actor_type=ActorType.ENGINE,
        action="DECISION_RECORDED",
        entity_type="decision",
        entity_id=decision.decision_id,
        occurred_at=stamp,
        payload={
            "action": decision.action,
            "status": decision.status,
            "amount": decision.amount,
            "headline": decision.headline,
            "requires_human_approval": decision.requires_human_approval,
            "rationale": list(decision.rationale),
        },
    )

    chain = chain.append(
        actor=actor,
        actor_type=ActorType.SYSTEM,
        action="RUN_COMPLETED",
        entity_type="run",
        entity_id=run_id,
        occurred_at=stamp,
        payload={"events": len(chain) + 1, "decision_id": decision.decision_id},
    )

    return PipelineResult(
        run_id=run_id,
        terms=terms,
        snapshot=snapshot,
        exposure=swarm.exposure,
        sensitivity_margin=swarm.sensitivity_margin,
        initial_margin=swarm.initial_margin,
        margin_call=swarm.margin_call,
        allocation=swarm.allocation,
        settlement=swarm.settlement,
        decision=decision,
        audit=chain,
        agent_actions=swarm.actions,
        plan_source=swarm.plan_source,
    )


def run_scenario(
    snapshot_id: str,
    as_of: date,
    run_id: str = "RUN-0001",
    *,
    posted_value: Money | None = None,
    terms: CSATerms | None = None,
    chain: AuditChain | None = None,
) -> PipelineResult:
    """Convenience entry point: load every fixture and run the pipeline.

    ``posted_value`` is accepted for scenarios that begin with collateral already
    held; the default is a zero balance.

    ``terms`` overrides the committed agreement fixture. The API passes the terms
    frozen from a reviewed extraction, so a reviewer's decision governs the
    calculation rather than merely being recorded next to it.
    """
    agreement = terms if terms is not None else load_agreement()
    portfolio = load_portfolio()
    inventory = load_inventory()
    snapshot = load_snapshot(snapshot_id)

    if snapshot.as_of != as_of:
        raise ValueError(
            f"Snapshot {snapshot_id} is as of {snapshot.as_of}, not {as_of}. "
            "The valuation date must match the pinned snapshot."
        )

    return run_pipeline(
        agreement,
        portfolio,
        inventory,
        snapshot,
        as_of,
        run_id=run_id,
        posted_value=posted_value,
        chain=chain,
    )
