"""Serialisation from core value objects to JSON-safe API responses.

The deterministic core knows nothing about HTTP, so the translation lives here. Two
rules govern it:

1. **Money is emitted as a decimal string**, never a JSON number. A float round-trip
   through JavaScript would silently lose precision on a nine-figure notional, and
   the frontend formats from the string.
2. **Every response carrying a computed number also carries its provenance** —
   ``engine_version``, ``snapshot_id``, ``as_of`` and ``trace_id``. That contract is
   asserted by a test, not left to habit.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from aether.agents.orchestrator import TOOL_REGISTRY
from aether.core.csa import MarginCallResult
from aether.core.csa_terms import CSATerms
from aether.core.decision import Decision
from aether.core.exposure import ExposureResult
from aether.core.im import InitialMarginResult
from aether.core.money import Money
from aether.core.optimize import AllocationLine, OptimizationResult
from aether.core.sensitivities import SensitivityMarginResult
from aether.core.settlement import SettlementInstruction, to_iso20022_xml, to_mt527
from aether.pipeline import PipelineResult

__all__ = [
    "money",
    "serialise_agents",
    "serialise_agreement",
    "serialise_audit",
    "serialise_comparison",
    "serialise_decision",
    "serialise_exposure",
    "serialise_margin_call",
    "serialise_optimization",
    "serialise_run",
    "serialise_sensitivity_margin",
    "serialise_settlement",
    "threshold_status",
]


def money(value: Money) -> dict[str, str]:
    """Money as a decimal string plus its currency. Never a float."""
    return {"amount": str(value.amount), "currency": value.currency.value}


def _dec(value: Decimal) -> str:
    return str(value)


def serialise_exposure(result: ExposureResult) -> dict[str, Any]:
    return {
        "netting_set_id": result.netting_set_id,
        "snapshot_id": result.snapshot_id,
        "as_of": result.as_of.isoformat(),
        "base_currency": result.base_currency.value,
        "exposure": money(result.exposure),
        "gross_positive": money(result.gross_positive),
        "netting_benefit": money(result.netting_benefit),
        "trade_count": result.trade_count,
        "trades": [
            {
                "trade_id": v.trade_id,
                "trade_type": v.trade_type,
                "native_value": money(v.native_value),
                "base_value": money(v.base_value),
                "detail": v.detail,
            }
            for v in result.trade_valuations
        ],
    }


def serialise_initial_margin(result: InitialMarginResult) -> dict[str, Any]:
    return {
        "method": result.method,
        "disclaimer": result.disclaimer,
        "gross_im": money(result.gross_im),
        "net_to_gross_ratio": _dec(result.net_to_gross_ratio),
        "initial_margin": money(result.initial_margin),
        "charged_to_vm_call": False,
        "charges": [
            {
                "trade_id": c.trade_id,
                "asset_class": c.asset_class,
                "notional": money(c.notional),
                "band": c.band,
                "rate": _dec(c.rate),
                "charge": money(c.charge),
            }
            for c in result.charges
        ],
    }


def serialise_margin_call(result: MarginCallResult) -> dict[str, Any]:
    return {
        "agreement_id": result.agreement_id,
        "netting_set_id": result.netting_set_id,
        "snapshot_id": result.snapshot_id,
        "as_of": result.as_of.isoformat(),
        "engine_version": result.engine_version,
        "base_currency": result.base_currency.value,
        "exposure": money(result.exposure),
        "transferor": result.transferor.value,
        "threshold": money(result.threshold),
        "independent_amount": money(result.independent_amount),
        "minimum_transfer_amount": money(result.minimum_transfer_amount),
        "credit_support_amount": money(result.credit_support_amount),
        "posted_value": money(result.posted_value),
        "unrounded_amount": money(result.unrounded_amount),
        "rounded_amount": money(result.rounded_amount),
        "call_amount": money(result.call_amount),
        "direction": result.direction.value,
        "gated_by_mta": result.gated_by_mta,
        "mta_before_rounding": result.mta_before_rounding,
        "has_call": result.has_call,
        "summary": result.summary,
        "waterfall": [
            {
                "label": step.label,
                "value": money(step.value),
                "clause": step.clause,
                "explanation": step.explanation,
                "is_gate": step.is_gate,
            }
            for step in result.trace
        ],
    }


def serialise_optimization(result: OptimizationResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "agreement_id": result.agreement_id,
        "snapshot_id": result.snapshot_id,
        "status": result.status.value,
        "message": result.message,
        "base_currency": result.base_currency.value,
        "required_value": money(result.required_value),
        "allocated_value": money(result.allocated_value),
        "total_cost": money(result.total_cost),
        "baseline_cost": money(result.baseline_cost),
        "saving": money(result.saving),
        "saving_percentage": _dec(result.saving_percentage),
        "lines": [_line(line) for line in result.lines],
        "baseline_lines": [_line(line) for line in result.baseline_lines],
        "shadow_prices": [
            {
                "name": s.name,
                "description": s.description,
                "shadow_price_bps": _dec(s.shadow_price_bps),
                "binding": s.binding,
            }
            for s in result.shadow_prices
        ],
        "excluded": [{"asset_id": a, "reason": r} for a, r in result.excluded],
        "considered": [_line(line) for line in result.considered],
        "cross_border": [_line(line) for line in result.cross_border_lines],
        "baseline_covers_requirement": result.baseline_covers,
    }


def _line(line: Any) -> dict[str, Any]:
    return {
        "asset_id": line.asset_id,
        "description": line.description,
        "asset_class": line.asset_class.value,
        "issuer": line.issuer,
        "currency": line.currency.value,
        "market_value_posted": money(line.market_value_posted),
        "effective_percentage": _dec(line.effective_percentage),
        "effective_value": money(line.effective_value),
        "funding_spread_bps": _dec(line.funding_spread_bps),
        "cost_per_effective_unit_bps": _dec(line.cost_per_effective_unit_bps),
        "annual_cost": money(line.annual_cost),
        "fx_haircut_applied": line.fx_haircut_applied,
        "fx_drag_bps": _dec(line.fx_drag_bps),
        "headline_rank": line.headline_rank,
        "effective_rank": line.effective_rank,
        "available_market_value": (
            money(line.available_market_value) if line.available_market_value else None
        ),
        "selected": line.selected,
        "not_selected_reason": line.not_selected_reason,
    }


def serialise_decision(decision: Decision) -> dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "agreement_id": decision.agreement_id,
        "snapshot_id": decision.snapshot_id,
        "as_of": decision.as_of.isoformat(),
        "engine_version": decision.engine_version,
        "action": decision.action.value,
        "status": decision.status.value,
        "transferor": decision.transferor.value,
        "amount": money(decision.amount),
        "exposure": money(decision.exposure),
        "credit_support_amount": money(decision.credit_support_amount),
        "initial_margin": money(decision.initial_margin),
        "allocation_cost": money(decision.allocation_cost),
        "baseline_cost": money(decision.baseline_cost),
        "saving": money(decision.saving),
        "saving_percentage": _dec(decision.saving_percentage),
        "asset_count": decision.asset_count,
        "headline": decision.headline,
        "rationale": list(decision.rationale),
        "requires_human_approval": decision.requires_human_approval,
        "disclaimer": decision.disclaimer,
        "simulated": decision.simulated,
    }


def serialise_audit(result: PipelineResult) -> dict[str, Any]:
    valid, break_at, message = result.audit.verify()
    return {
        "chain_id": result.audit.chain_id,
        "head_hash": result.audit.head_hash,
        "verified": valid,
        "break_at": break_at,
        "verification_message": message,
        "events": [
            {
                "seq": e.seq,
                "actor": e.actor,
                "actor_type": e.actor_type.value,
                "action": e.action,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "occurred_at": e.occurred_at,
                "hash": e.hash,
                "prev_hash": e.prev_hash,
                "payload": _jsonable(e.payload),
            }
            for e in result.audit.events
        ],
    }


def _jsonable(value: Any) -> Any:
    """Recursively convert Money and Decimal so the payload survives JSON encoding."""
    if isinstance(value, Money):
        return money(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "value") and hasattr(value, "name"):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def serialise_agreement(terms: CSATerms) -> dict[str, Any]:
    return {
        "agreement_id": terms.agreement_id,
        "netting_set_id": terms.netting_set_id,
        "csa_type": terms.csa_type,
        "governing_law": terms.governing_law,
        "terms_version": terms.terms_version,
        "base_currency": terms.base_currency.value,
        "eligible_currencies": sorted(c.value for c in terms.eligible_currencies),
        "fx_haircut_pct": _dec(terms.fx_haircut_pct),
        "mta_before_rounding": terms.mta_before_rounding,
        "excluded_issuers": sorted(terms.excluded_issuers),
        "party_a": _party(terms.party_a),
        "party_b": _party(terms.party_b),
        "rounding": {
            "increment": money(terms.rounding.increment),
            "delivery_direction": terms.rounding.delivery_direction.value,
            "return_direction": terms.rounding.return_direction.value,
        },
        "eligible_collateral": [
            {
                "ref": item.ref,
                "asset_class": item.asset_class.value,
                "issuer_type": item.issuer_type.value,
                "issuer": item.issuer,
                "currency": item.currency.value if item.currency else None,
                "non_base_currency_only": item.non_base_currency_only,
                "min_maturity_years": _opt(item.min_maturity_years),
                "max_maturity_years": _opt(item.max_maturity_years),
                "min_rating": item.min_rating,
                "valuation_percentage": _dec(item.valuation_percentage),
            }
            for item in terms.eligible_collateral
        ],
        "concentration_limits": [
            {"scope": limit.scope.value, "limit_percentage": _dec(limit.limit_percentage)}
            for limit in terms.concentration_limits
        ],
        "simulated": terms.simulated,
    }


def _party(party: Any) -> dict[str, Any]:
    return {
        "party": party.party.value,
        "threshold": money(party.threshold),
        "minimum_transfer_amount": money(party.minimum_transfer_amount),
        "independent_amount": money(party.independent_amount),
    }


def serialise_sensitivity_margin(result: SensitivityMarginResult) -> dict[str, Any]:
    """Risk-weighted sensitivity margin, with the sensitivities behind it."""
    return {
        "netting_set_id": result.netting_set_id,
        "snapshot_id": result.snapshot_id,
        "as_of": result.as_of.isoformat(),
        "method": result.method,
        "interest_rate_margin": money(result.interest_rate_margin),
        "fx_margin": money(result.fx_margin),
        "vega_margin": money(result.vega_margin),
        "total_margin": money(result.total_margin),
        "disclaimer": result.disclaimer,
        "vega_note": result.vega_note,
        "buckets": [
            {
                "risk_class": bucket.risk_class.value,
                "bucket": bucket.bucket,
                "sensitivity_count": bucket.sensitivity_count,
                "weighted_sum": money(bucket.weighted_sum),
                "margin": money(bucket.margin),
            }
            for bucket in result.buckets
        ],
        "sensitivities": [
            {
                "risk_class": s.risk_class.value,
                "measure": s.measure.value,
                "bucket": s.bucket,
                "label": s.label,
                "tenor_years": s.tenor_years,
                "value": money(s.value),
                "risk_weight": _dec(s.risk_weight),
                "weighted_value": money(s.weighted_value),
            }
            for s in result.material_sensitivities
        ],
    }


def serialise_settlement(instruction: SettlementInstruction | None) -> dict[str, Any] | None:
    """The generated instruction, plus both message renderings.

    Rendered here rather than behind a separate endpoint, because the point of the
    screen is that a reader can see the actual message text beside the allocation it
    was generated from.
    """
    if instruction is None:
        return None
    return {
        "instruction_id": instruction.instruction_id,
        "agreement_id": instruction.agreement_id,
        "netting_set_id": instruction.netting_set_id,
        "snapshot_id": instruction.snapshot_id,
        "as_of": instruction.as_of.isoformat(),
        "value_date": instruction.value_date.isoformat(),
        "direction": instruction.direction.value,
        "deliverer": instruction.deliverer,
        "deliverer_bic": instruction.deliverer_bic,
        "receiver": instruction.receiver,
        "receiver_bic": instruction.receiver_bic,
        "call_amount": money(instruction.call_amount),
        "collateral_value": money(instruction.collateral_value),
        "is_balanced": instruction.is_balanced,
        "status": instruction.status.value,
        "message_types": list(instruction.message_types),
        "engine_version": instruction.engine_version,
        "transmitted": False,
        "disclaimer": instruction.disclaimer,
        "legs": [
            {
                "sequence": leg.sequence,
                "asset_id": leg.asset_id,
                "description": leg.description,
                "asset_class": leg.asset_class,
                "currency": leg.currency.value,
                "market_value": money(leg.market_value),
                "valuation_percentage": _dec(leg.valuation_percentage),
                "collateral_value": money(leg.collateral_value),
                "safekeeping_account": leg.safekeeping_account,
                "delivery_method": leg.delivery_method,
            }
            for leg in instruction.legs
        ],
        "iso20022_xml": to_iso20022_xml(instruction),
        "mt527": to_mt527(instruction),
    }


#: What each agent is responsible for. Served as data so the UI cannot invent a
#: fourth agent or rename one of the three.
AGENT_ROSTER: tuple[tuple[str, str, str], ...] = (
    (
        "LEGAL_CLAUSE_AGENT",
        "Legal-Clause Agent",
        "Reads the Annex. Produces typed, cited, confidence-scored terms and routes "
        "anything ambiguous to a human before it can reach the engine.",
    ),
    (
        "RISK_ENGINE_AGENT",
        "Risk-Engine Agent",
        "Routes deterministic valuation, sensitivity and margin tools against a "
        "pinned market snapshot.",
    ),
    (
        "COLLATERAL_OPTIMIZER_AGENT",
        "Collateral-Optimizer Agent",
        "Decides whether collateral must be selected, runs the linear program, and "
        "renders the settlement instruction.",
    ),
)


def serialise_agents(result: PipelineResult) -> dict[str, Any]:
    """The swarm's trace: which agent called which tool, and why.

    ``arguments`` are rendered verbatim so a reader can see for themselves that no
    monetary value appears on the agent side of the boundary.
    """
    return {
        "plan_source": result.plan_source.value,
        "roster": [
            {"role": role, "title": title, "responsibility": responsibility}
            for role, title, responsibility in AGENT_ROSTER
        ],
        "actions": [
            {
                "agent": action.agent.value,
                "tool": action.tool,
                "intent": action.intent,
                "arguments": dict(action.arguments),
                "outcome": action.outcome,
            }
            for action in result.agent_actions
        ],
        "tools": [
            {
                "name": spec.name,
                "owner": spec.owner.value,
                "description": spec.description,
                "required_arguments": list(spec.required_arguments),
                "produces": spec.produces,
            }
            for spec in TOOL_REGISTRY
        ],
        "boundary": (
            "An agent may pass identifiers and flags. It cannot pass a number: "
            "ToolCall rejects any float, Decimal or Money argument at construction. "
            "Every monetary value in this run came from an engine event."
        ),
    }


def _opt(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def serialise_run(result: PipelineResult) -> dict[str, Any]:
    """The complete pipeline output — what the dashboard renders."""
    return {
        "run_id": result.run_id,
        # The reproducibility contract names trace_id; run_id is that identifier, and
        # it is emitted under both names so the contract is satisfied literally.
        "trace_id": result.run_id,
        "as_of": result.snapshot.as_of.isoformat(),
        "engine_version": result.margin_call.engine_version,
        "snapshot": {
            "snapshot_id": result.snapshot.snapshot_id,
            "label": result.snapshot.label,
            "as_of": result.snapshot.as_of.isoformat(),
            "simulated": result.snapshot.simulated,
        },
        "agreement": serialise_agreement(result.terms),
        "exposure": serialise_exposure(result.exposure),
        "sensitivity_margin": serialise_sensitivity_margin(result.sensitivity_margin),
        "initial_margin": serialise_initial_margin(result.initial_margin),
        "margin_call": serialise_margin_call(result.margin_call),
        "allocation": serialise_optimization(result.allocation),
        "settlement": serialise_settlement(result.settlement),
        "agents": serialise_agents(result),
        "decision": serialise_decision(result.decision),
        "audit": serialise_audit(result),
    }


# ---------------------------------------------------------------- comparison

#: Which figures a before/after comparison reports, in the order a reader needs
#: them: what the market did, what that did to exposure, what the CSA then
#: required, and what the optimiser posted against it.
#:
#: Each entry is ``(id, label, basis)``. Values are resolved in :func:`_metric_value`
#: so this table stays readable as documentation of what the comparison claims.
COMPARISON_METRICS: tuple[tuple[str, str, str], ...] = (
    (
        "portfolio_mtm",
        "Portfolio mark-to-market",
        "Net present value of the netting set in base currency, signed from Party A's "
        "perspective. Negative means Party A is out of the money.",
    ),
    (
        "gross_positive",
        "Gross positive value",
        "Sum of the in-the-money trades, before netting.",
    ),
    (
        "netting_benefit",
        "Netting benefit",
        "What close-out netting removes from the gross figure.",
    ),
    (
        "credit_support_amount",
        "Credit Support Amount",
        "Paragraph 2(c): exposure less Threshold, plus any Independent Amount. The "
        "margin requirement, before the MTA gate and rounding.",
    ),
    (
        "threshold",
        "Threshold",
        "The Transferor's unsecured allowance. Changes when the Transferor changes.",
    ),
    (
        "call_amount",
        "Collateral requirement (transfer)",
        "The Delivery or Return Amount after the Minimum Transfer Amount gate and "
        "directional rounding.",
    ),
    (
        "eligible_pool",
        "Eligible collateral available",
        "Market value of every inventory asset passing the CSA eligibility schedule, "
        "converted to base currency at the pinned snapshot's FX.",
    ),
    (
        "collateral_market_value",
        "Collateral encumbered (market value)",
        "Market value of the assets the optimiser selected, before haircut.",
    ),
    (
        "collateral_post_haircut",
        "Collateral delivered (post-haircut)",
        "What those assets are worth as credit support after the schedule valuation "
        "percentage and any FX haircut.",
    ),
    (
        "funding_cost",
        "Annual funding cost of the allocation",
        "Cost of encumbering the selected assets for a year at their funding spreads.",
    ),
    (
        "sensitivity_im",
        "Sensitivity initial margin",
        "Risk-weighted aggregation of measured sensitivities. Indicative, and not "
        "charged to the variation margin call.",
    ),
    (
        "schedule_im",
        "Schedule initial margin",
        "BCBS-IOSCO standardised grid applied to notional. Indicative, and not "
        "charged to the variation margin call.",
    ),
)


def _eligible_pool(result: PipelineResult) -> Money:
    """Base-currency market value of the eligible collateral pool.

    Converted with :meth:`MarketSnapshot.convert` — the same pinned FX the optimizer
    itself uses at ``optimize.py`` — so this figure cannot disagree with the
    allocation it sits beside. Assets the eligibility schedule excluded are absent
    from ``considered`` and are therefore not counted.
    """
    base = result.terms.base_currency
    total = Money.zero(base)
    if result.allocation is None:
        return total
    for line in result.allocation.considered:
        if line.available_market_value is None:
            continue
        total = total + result.snapshot.convert(line.available_market_value, base)
    return total


def _collateral_market_value(result: PipelineResult) -> Money:
    """Market value of what was actually selected, before haircut."""
    base = result.terms.base_currency
    total = Money.zero(base)
    if result.allocation is None:
        return total
    for line in result.allocation.lines:
        total = total + line.market_value_posted
    return total


def _metric_value(result: PipelineResult, metric_id: str) -> Money:
    """Read one comparison figure off a completed run.

    Every entry returns a value the engine already computed. Nothing is derived here
    beyond summation of like-currency amounts in :class:`~decimal.Decimal`.
    """
    base = result.terms.base_currency
    readers: dict[str, Callable[[], Money]] = {
        "portfolio_mtm": lambda: result.exposure.exposure,
        "gross_positive": lambda: result.exposure.gross_positive,
        "netting_benefit": lambda: result.exposure.netting_benefit,
        "credit_support_amount": lambda: result.margin_call.credit_support_amount,
        "threshold": lambda: result.margin_call.threshold,
        "call_amount": lambda: result.margin_call.call_amount,
        "eligible_pool": lambda: _eligible_pool(result),
        "collateral_market_value": lambda: _collateral_market_value(result),
        "collateral_post_haircut": lambda: (
            Money.zero(base) if result.allocation is None else result.allocation.allocated_value
        ),
        "funding_cost": lambda: (
            Money.zero(base) if result.allocation is None else result.allocation.total_cost
        ),
        "sensitivity_im": lambda: result.sensitivity_margin.total_margin,
        "schedule_im": lambda: result.initial_margin.initial_margin,
    }
    reader = readers.get(metric_id)
    if reader is None:
        raise KeyError(f"Unknown comparison metric '{metric_id}'.")
    return reader()


#: Metrics that only exist once the optimizer has run. When no Delivery Amount is
#: due the optimizer is not invoked at all, and reporting these as ``0.00`` would
#: say "no collateral was available" when the truth is "the question was never
#: asked". They are marked unavailable instead.
ALLOCATION_DEPENDENT: frozenset[str] = frozenset(
    {
        "eligible_pool",
        "collateral_market_value",
        "collateral_post_haircut",
        "funding_cost",
    }
)


def _metric_available(result: PipelineResult, metric_id: str) -> bool:
    if metric_id in ALLOCATION_DEPENDENT:
        return result.allocation is not None
    return True


def _direction(delta: Decimal) -> str:
    if delta > 0:
        return "UP"
    if delta < 0:
        return "DOWN"
    return "FLAT"


def threshold_status(result: PipelineResult) -> dict[str, Any]:
    """Where this run sits against the CSA Threshold.

    Three states, each read from the margin call rather than inferred from a
    magnitude:

    ``WITHIN``   exposure did not exceed the Threshold, so no Credit Support Amount
                 arises.
    ``WARNING``  the Threshold was exceeded but the Minimum Transfer Amount gated the
                 call, so nothing transfers today.
    ``BREACHED`` the Threshold was exceeded and a transfer is due.
    """
    call = result.margin_call
    exceeded = call.credit_support_amount.amount > 0

    if not exceeded:
        state = "WITHIN"
        message = (
            "Exposure sits inside the Threshold. No Credit Support Amount arises "
            "under Paragraph 2(c)."
        )
    elif call.gated_by_mta or call.direction.value == "NONE":
        state = "WARNING"
        message = (
            "The Threshold is exceeded, but the resulting amount is below the "
            "Minimum Transfer Amount. Nothing transfers today."
        )
    else:
        state = "BREACHED"
        message = "The Threshold is exceeded and a transfer is due under Paragraph 2."

    return {
        "state": state,
        "message": message,
        "exposure": money(call.exposure),
        "threshold": money(call.threshold),
        "credit_support_amount": money(call.credit_support_amount),
        "minimum_transfer_amount": money(call.minimum_transfer_amount),
        "call_amount": money(call.call_amount),
        "transferor": call.transferor.value,
        "gated_by_mta": call.gated_by_mta,
    }


def _allocation_lines(result: PipelineResult) -> dict[str, AllocationLine]:
    if result.allocation is None:
        return {}
    return {line.asset_id: line for line in result.allocation.lines}


def serialise_comparison(
    before: PipelineResult,
    after: PipelineResult,
    before_meta: dict[str, Any],
    after_meta: dict[str, Any],
) -> dict[str, Any]:
    """Two deterministic runs, and the exact difference between them.

    Every delta is ``Decimal`` subtraction of two figures the engine computed. No
    figure here is estimated, interpolated or modelled: the payload reports what
    changed between two pinned market snapshots and nothing else. Doing the
    subtraction server-side keeps money arithmetic in ``Decimal`` and gives the UI
    one source of truth to render.
    """
    if before.terms.base_currency != after.terms.base_currency:
        raise ValueError(
            "Cannot compare runs in different base currencies: "
            f"{before.terms.base_currency} and {after.terms.base_currency}."
        )

    metrics: list[dict[str, Any]] = []
    for metric_id, label, basis in COMPARISON_METRICS:
        lhs = _metric_value(before, metric_id)
        rhs = _metric_value(after, metric_id)
        lhs_ok = _metric_available(before, metric_id)
        rhs_ok = _metric_available(after, metric_id)
        comparable = lhs_ok and rhs_ok
        delta = rhs - lhs
        metrics.append(
            {
                "id": metric_id,
                "label": label,
                "basis": basis,
                "before": money(lhs),
                "after": money(rhs),
                "before_available": lhs_ok,
                "after_available": rhs_ok,
                "comparable": comparable,
                "delta": money(delta) if comparable else None,
                "direction": _direction(delta.amount) if comparable else "NOT_COMPARABLE",
                "unavailable_reason": (
                    ""
                    if comparable
                    else (
                        "No Delivery Amount was due at one of these snapshots, so the "
                        "optimizer was never invoked. There is no figure to compare, "
                        "which is not the same as a figure of zero."
                    )
                ),
            }
        )

    before_lines = _allocation_lines(before)
    after_lines = _allocation_lines(after)
    base = after.terms.base_currency

    allocation_rows: list[dict[str, Any]] = []
    for asset_id in sorted(set(before_lines) | set(after_lines)):
        lhs_line = before_lines.get(asset_id)
        rhs_line = after_lines.get(asset_id)
        reference = rhs_line if rhs_line is not None else lhs_line
        if reference is None:  # unreachable: the id came from one of the two
            continue
        lhs_value = lhs_line.market_value_posted if lhs_line else Money.zero(base)
        rhs_value = rhs_line.market_value_posted if rhs_line else Money.zero(base)
        delta = rhs_value - lhs_value

        if lhs_line is None:
            status = "ADDED"
        elif rhs_line is None:
            status = "REMOVED"
        elif delta.amount > 0:
            status = "INCREASED"
        elif delta.amount < 0:
            status = "DECREASED"
        else:
            status = "UNCHANGED"

        allocation_rows.append(
            {
                "asset_id": asset_id,
                "description": reference.description,
                "asset_class": reference.asset_class.value,
                "currency": reference.currency.value,
                "before": money(lhs_value),
                "after": money(rhs_value),
                "delta": money(delta),
                "status": status,
            }
        )

    return {
        "before": {
            **before_meta,
            "run_id": before.run_id,
            "snapshot_id": before.snapshot.snapshot_id,
            "snapshot_label": before.snapshot.label,
            "as_of": before.snapshot.as_of.isoformat(),
            "decision": before.decision.action,
            "transferor": before.margin_call.transferor.value,
            "threshold_status": threshold_status(before),
            "asset_count": len(before_lines),
        },
        "after": {
            **after_meta,
            "run_id": after.run_id,
            "snapshot_id": after.snapshot.snapshot_id,
            "snapshot_label": after.snapshot.label,
            "as_of": after.snapshot.as_of.isoformat(),
            "decision": after.decision.action,
            "transferor": after.margin_call.transferor.value,
            "threshold_status": threshold_status(after),
            "asset_count": len(after_lines),
        },
        "base_currency": base.value,
        "engine_version": after.margin_call.engine_version,
        "metrics": metrics,
        "allocation_delta": allocation_rows,
        "transferor_changed": (before.margin_call.transferor != after.margin_call.transferor),
        "method": (
            "Two independent deterministic runs against two pinned market snapshots. "
            "Every delta is Decimal subtraction of engine-computed figures. Nothing "
            "is interpolated, modelled or estimated."
        ),
        "simulated": True,
    }
