"""The AETHER guide agent.

The assistant a user talks to. It answers questions about the run on screen and about
the application itself — where to go, what a panel means, what to do next.

.. rubric:: The boundary

This is the one place in the product where a model composes prose that a user reads
next to financial figures, so the boundary is drawn tightly:

**The model orchestrates. It never authors a figure.** Every number reachable by the
assistant comes out of a tool in this module, and every tool reads it from the
deterministic run payload the panels themselves render. The model chooses which tools
to call and writes the sentences between them.

That is enforced three ways, not asserted once:

1. *Tools are the only source.* There is no tool that computes. Each one selects
   named fields out of an engine result and returns them with the paths it read.
2. *Permissions are checked in the tool, not in the prompt.* A model instructed not
   to reveal contract terms is a request; a tool that returns ``NOT_PERMITTED`` is a
   gate. The refusal names the role that does hold the permission.
3. *The prose is verified after generation.* :func:`stray_figures` re-reads the
   model's answer and rejects any monetary, percentage or basis-point figure that is
   not present in the tool results behind it. A violation does not get edited or
   apologised for — the whole answer is discarded and the deterministic composition
   is served instead.

.. rubric:: Both modes answer

``AETHER_MODE=live`` runs the model loop. ``AETHER_MODE=replay`` — the demo path, and
the default — runs :func:`route`, a keyword router over the *same tools*, and composes
the answer from the same evidence. So the figures are identical either way and the
demo needs no network. What live mode buys is understanding a question that the
keyword router does not recognise, and stitching several tools into one answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from aether.agents.prompts import GUIDE_PROMPT, GUIDE_PROMPT_VERSION
from aether.agents.screens import SCREENS, WORKFLOW, Screen, screen_by_id, screens_for
from aether.config import Mode, Settings, install_tls_trust
from aether.roles import PERMISSION_LABELS, ROLE_MANDATES, permissions_of, roles_holding

__all__ = [
    "Evidence",
    "GuideAnswer",
    "GuideContext",
    "GuideField",
    "answer",
    "route",
    "starters",
    "stray_figures",
]

JSON = dict[str, Any]

#: How many times the model may call tools before the loop is cut. A guide answer
#: needs two or three; anything beyond this is a model that has lost the thread, and
#: the deterministic composition of whatever it did retrieve is a better answer than
#: letting it continue.
MAX_TOOL_TURNS = 6

#: Guide answers are short by construction — the prompt asks for two to four
#: sentences and the figures are rendered outside the prose.
MAX_REPLY_TOKENS = 1024


# --------------------------------------------------------------------- values


@dataclass(frozen=True)
class GuideField:
    """One labelled figure. The value is a string exactly as the engine emitted it."""

    label: str
    value: str
    headline: bool = False


@dataclass(frozen=True)
class Evidence:
    """What one tool returned.

    Rendered to the user as a titled block of figures, and handed to the model as
    JSON. Both see the same thing, which is the point: the user can check the prose
    against the evidence it was written from.
    """

    tool: str
    status: str
    title: str
    text: str
    fields: tuple[GuideField, ...] = ()
    #: The screen displaying these same values.
    source: str = "—"
    href: str | None = None
    #: Paths read out of the run payload, so a sceptic can check.
    paths: tuple[str, ...] = ()

    def as_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "title": self.title,
                "summary": self.text,
                "figures": [{"label": f.label, "value": f.value} for f in self.fields],
                "screen": self.source,
                "route": self.href,
                "paths": list(self.paths),
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class GuideContext:
    """Everything the tools may read. Assembled by the API from a real run."""

    run: JSON
    comparison: JSON | None
    role: str | None
    scenario_name: str
    baseline_name: str
    #: Extraction fields still awaiting a reviewer, if an extraction is in session.
    pending_review: int = 0

    @property
    def permissions(self) -> frozenset[str]:
        return permissions_of(self.role)

    def may(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(frozen=True)
class GuideAnswer:
    """One turn of the assistant."""

    status: str
    reply: str
    evidence: tuple[Evidence, ...] = ()
    #: ``(label, route)`` pairs the UI renders as navigation buttons.
    actions: tuple[tuple[str, str], ...] = ()
    follow_ups: tuple[str, ...] = ()
    #: ``model`` when the answer was composed by the agent, ``deterministic`` when
    #: the keyword router answered — either because the mode is replay, or because
    #: the model's answer failed verification.
    route: str = "deterministic"
    guard: str = "OK"
    model_id: str | None = None
    tool_calls: int = 0
    prompt_version: str = GUIDE_PROMPT_VERSION


# ---------------------------------------------------------------- formatting


def _money(value: JSON) -> str:
    """Money exactly as the engine emitted it: a decimal string and its currency."""
    return f"{value['currency']} {value['amount']}"


def _pct(value: str) -> str:
    return f"{value}%"


def _refuse(tool: str, permission: str) -> Evidence:
    holders = ", ".join(roles_holding(permission))
    label = PERMISSION_LABELS.get(permission, permission)
    return Evidence(
        tool=tool,
        status="NOT_PERMITTED",
        title="Not permitted for this role",
        text=(
            f'Answering that needs the "{permission}" permission ({label.lower()}). '
            f"Your role does not hold it. These roles do: {holders}."
        ),
        source="Access control",
    )


def _unavailable(tool: str, text: str) -> Evidence:
    return Evidence(tool=tool, status="UNAVAILABLE", title="Not available", text=text)


# --------------------------------------------------------------------- tools


def _tool_list_screens(ctx: GuideContext, args: JSON) -> Evidence:
    reachable = screens_for(ctx.permissions)
    if not reachable:
        return _unavailable("list_screens", "You are not signed in, so no screen is reachable.")

    return Evidence(
        tool="list_screens",
        status="ANSWERED",
        title="Screens you can reach",
        text=(
            f"As {ctx.role} you can reach {len(reachable)} of {len(SCREENS)} screens. "
            "They are ordered as the pipeline runs: contract, exposure, margin, "
            "optimisation, decision, record."
        ),
        fields=tuple(GuideField(label=s.label, value=s.route) for s in reachable),
        source="Navigation",
    )


def _tool_describe_screen(ctx: GuideContext, args: JSON) -> Evidence:
    screen_id = str(args.get("screen_id", ""))
    screen = screen_by_id(screen_id)
    if screen is None:
        known = ", ".join(s.id for s in SCREENS)
        return _unavailable(
            "describe_screen",
            f"There is no screen called '{screen_id}'. The screens are: {known}.",
        )
    if not ctx.may(screen.permission):
        return _refuse("describe_screen", screen.permission)

    lines = [f"Shows: {item}." for item in screen.shows]
    lines += [f"You can: {item}." for item in screen.actions]
    return Evidence(
        tool="describe_screen",
        status="ANSWERED",
        title=screen.label,
        text=f"{screen.purpose} " + " ".join(lines),
        fields=(
            GuideField(label="Route", value=screen.route, headline=True),
            GuideField(label="In the navigation bar", value="yes" if screen.in_nav else "no"),
            GuideField(label="Permission", value=screen.permission),
        ),
        source=screen.label,
        href=screen.route,
    )


#: Which permission each figure topic sits behind. Anything not named here is desk
#: data, visible to every signed-in role.
_TOPIC_PERMISSION: dict[str, str] = {
    "audit": "view:audit",
    "agreement": "view:contract",
}

_TOPICS: tuple[str, ...] = (
    "exposure",
    "margin_call",
    "threshold",
    "initial_margin",
    "allocation",
    "decision",
    "audit",
    "agreement",
    "provenance",
)


def _figures_exposure(run: JSON) -> Evidence:
    exposure = run["exposure"]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Exposure",
        text=(
            f"Mark-to-market of the netting set across {exposure['trade_count']} trades, "
            "valued at the pinned snapshot. Close-out netting removes the netting "
            "benefit from the gross positive figure."
        ),
        fields=(
            GuideField("Exposure", _money(exposure["exposure"]), headline=True),
            GuideField("Gross positive value", _money(exposure["gross_positive"])),
            GuideField("Netting benefit", _money(exposure["netting_benefit"])),
            GuideField("Trades", str(exposure["trade_count"])),
        ),
        source="Exposure & Margin",
        href="/exposure",
        paths=(
            "exposure.exposure",
            "exposure.gross_positive",
            "exposure.netting_benefit",
            "exposure.trade_count",
        ),
    )


def _figures_margin_call(run: JSON) -> Evidence:
    call = run["margin_call"]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Margin call",
        text=str(call["summary"]),
        fields=(
            GuideField("Call amount", _money(call["call_amount"]), headline=True),
            GuideField("Direction", str(call["direction"])),
            GuideField("Transferor", str(call["transferor"])),
            GuideField("Credit Support Amount", _money(call["credit_support_amount"])),
            GuideField("Threshold", _money(call["threshold"])),
            GuideField("Minimum Transfer Amount", _money(call["minimum_transfer_amount"])),
            GuideField("Already posted", _money(call["posted_value"])),
            GuideField("Gated by the MTA", "yes" if call["gated_by_mta"] else "no"),
        ),
        source="Exposure & Margin",
        href="/exposure",
        paths=(
            "margin_call.call_amount",
            "margin_call.direction",
            "margin_call.credit_support_amount",
            "margin_call.threshold",
            "margin_call.minimum_transfer_amount",
            "margin_call.posted_value",
            "margin_call.gated_by_mta",
        ),
    )


def _figures_threshold(run: JSON) -> Evidence:
    status = run["threshold_status"]
    call = run["margin_call"]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Threshold status",
        text=str(status["message"]),
        fields=(
            GuideField("State", str(status["state"]), headline=True),
            GuideField("Exposure", _money(call["exposure"])),
            GuideField("Threshold", _money(call["threshold"])),
            GuideField("Credit Support Amount", _money(call["credit_support_amount"])),
        ),
        source="Exposure & Margin",
        href="/exposure",
        paths=("threshold_status.state", "margin_call.threshold", "margin_call.exposure"),
    )


def _figures_initial_margin(run: JSON) -> Evidence:
    im = run["initial_margin"]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Initial margin",
        text=f"{im['method']}. {im['disclaimer']}",
        fields=(
            GuideField("Initial margin", _money(im["initial_margin"]), headline=True),
            GuideField("Gross IM", _money(im["gross_im"])),
            GuideField("Net-to-gross ratio", str(im["net_to_gross_ratio"])),
            GuideField(
                "Charged to this VM call",
                "yes" if im["charged_to_vm_call"] else "no",
            ),
        ),
        source="Exposure & Margin",
        href="/exposure",
        paths=("initial_margin.initial_margin", "initial_margin.gross_im"),
    )


def _figures_allocation(run: JSON) -> Evidence:
    allocation = run["allocation"]
    if allocation["status"] == "NOT_REQUIRED":
        return Evidence(
            tool="get_run_figures",
            status="ANSWERED",
            title="Allocation",
            text=(
                "No Delivery Amount was due at this snapshot, so the optimiser was "
                "never invoked. There is no allocation to explain."
            ),
            fields=(GuideField("Status", "NOT_REQUIRED", headline=True),),
            source="Optimisation",
            href="/optimisation",
            paths=("allocation.status",),
        )

    selected = [line for line in allocation["lines"] if line["selected"]]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Allocation",
        text=str(allocation["message"]),
        fields=(
            GuideField("Allocated value", _money(allocation["allocated_value"]), headline=True),
            GuideField("Required value", _money(allocation["required_value"])),
            GuideField("Assets posted", str(len(selected))),
            GuideField("Annual funding cost", _money(allocation["total_cost"])),
            GuideField("Cash-first baseline cost", _money(allocation["baseline_cost"])),
            GuideField("Saving against baseline", _money(allocation["saving"])),
            GuideField("Saving", _pct(str(allocation["saving_percentage"]))),
        ),
        source="Optimisation",
        href="/optimisation",
        paths=(
            "allocation.allocated_value",
            "allocation.required_value",
            "allocation.total_cost",
            "allocation.baseline_cost",
            "allocation.saving",
            "allocation.saving_percentage",
        ),
    )


def _figures_decision(run: JSON) -> Evidence:
    decision = run["decision"]
    approval = run.get("approval")
    fields = [
        GuideField("Action", str(decision["action"]), headline=True),
        GuideField("Status", str(decision["status"])),
        GuideField("Amount", _money(decision["amount"])),
        GuideField("Transferor", str(decision["transferor"])),
        GuideField(
            "Needs human approval",
            "yes" if decision["requires_human_approval"] else "no",
        ),
    ]
    if approval:
        fields.append(GuideField("Approved by", str(approval.get("approver", "—"))))

    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Decision",
        text=f"{decision['headline']} {decision['disclaimer']}",
        fields=tuple(fields),
        source="Dashboard",
        href="/",
        paths=("decision.action", "decision.status", "decision.amount", "approval"),
    )


def _figures_audit(run: JSON) -> Evidence:
    audit = run["audit"]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Audit chain",
        text=str(audit["verification_message"]),
        fields=(
            GuideField("Verified", "yes" if audit["verified"] else "no", headline=True),
            GuideField("Events", str(len(audit["events"]))),
            GuideField("Head hash", str(audit["head_hash"])),
            GuideField("Chain", str(audit["chain_id"])),
        ),
        source="Audit Trail",
        href="/audit",
        paths=("audit.verified", "audit.head_hash", "audit.events"),
    )


def _figures_agreement(run: JSON) -> Evidence:
    agreement = run["agreement"]
    frozen = run["terms_source"] == "FROZEN_FROM_REVIEWED_EXTRACTION"
    provenance = (
        "These terms were frozen from a reviewed extraction, so a reviewer's decision "
        "governs this calculation."
        if frozen
        else "These are the committed fixture terms; no extraction has been reviewed "
        "and frozen in this session."
    )
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Governing agreement",
        text=(
            f"Agreement {agreement['agreement_id']} — {agreement['csa_type']} under "
            f"{agreement['governing_law']}, terms version "
            f"{agreement['terms_version']}. {provenance}"
        ),
        fields=(
            GuideField(
                "Party A Threshold", _money(agreement["party_a"]["threshold"]), headline=True
            ),
            GuideField("Party B Threshold", _money(agreement["party_b"]["threshold"])),
            GuideField(
                "Minimum Transfer Amount",
                _money(agreement["party_a"]["minimum_transfer_amount"]),
            ),
            GuideField("Rounding increment", _money(agreement["rounding"]["increment"])),
            # The rate as the engine holds it: a decimal in [0, 1]. Rescaling it to a
            # percentage here would be arithmetic, and no tool does arithmetic.
            GuideField("FX haircut", str(agreement["fx_haircut_pct"])),
            GuideField("Base currency", str(agreement["base_currency"])),
            GuideField("Eligible currencies", ", ".join(agreement["eligible_currencies"])),
            GuideField(
                "Excluded issuers",
                ", ".join(agreement["excluded_issuers"]) or "none",
            ),
            GuideField(
                "Eligible collateral",
                f"{len(agreement['eligible_collateral'])} schedule items",
            ),
            GuideField("Terms source", str(run["terms_source"])),
        ),
        source="Contracts",
        href="/review",
        paths=(
            "agreement.agreement_id",
            "agreement.party_a.threshold",
            "agreement.party_b.threshold",
            "agreement.rounding.increment",
            "agreement.fx_haircut_pct",
            "terms_source",
        ),
    )


def _figures_provenance(run: JSON) -> Evidence:
    snapshot = run["snapshot"]
    return Evidence(
        tool="get_run_figures",
        status="ANSWERED",
        title="Provenance",
        text=(
            "Every figure in this run comes from a pinned market snapshot, which is "
            "why re-running reproduces it exactly. The data is SIMULATED — it is not "
            "real institutional data and no transaction is executed."
            if snapshot["simulated"]
            else "This snapshot is not marked as simulated."
        ),
        fields=(
            GuideField("Snapshot", str(snapshot["snapshot_id"]), headline=True),
            GuideField("Label", str(snapshot["label"])),
            GuideField("As of", str(run["as_of"])),
            GuideField("Simulated data", "yes" if snapshot["simulated"] else "no"),
            GuideField("Engine version", str(run["engine_version"])),
            GuideField("Trace", str(run["trace_id"])),
        ),
        source="Methodology",
        href="/methodology",
        paths=("snapshot.snapshot_id", "snapshot.simulated", "engine_version", "trace_id"),
    )


_FIGURE_TOPICS: dict[str, Callable[[JSON], Evidence]] = {
    "exposure": _figures_exposure,
    "margin_call": _figures_margin_call,
    "threshold": _figures_threshold,
    "initial_margin": _figures_initial_margin,
    "allocation": _figures_allocation,
    "decision": _figures_decision,
    "audit": _figures_audit,
    "agreement": _figures_agreement,
    "provenance": _figures_provenance,
}


def _tool_get_run_figures(ctx: GuideContext, args: JSON) -> Evidence:
    topic = str(args.get("topic", ""))
    reader = _FIGURE_TOPICS.get(topic)
    if reader is None:
        return _unavailable(
            "get_run_figures",
            f"'{topic}' is not a topic I hold. The topics are: {', '.join(_TOPICS)}.",
        )

    permission = _TOPIC_PERMISSION.get(topic, "view:desk")
    if not ctx.may(permission):
        return _refuse("get_run_figures", permission)

    return reader(ctx.run)


def _tool_compare_runs(ctx: GuideContext, args: JSON) -> Evidence:
    if not ctx.may("view:desk"):
        return _refuse("compare_runs", "view:desk")
    if ctx.comparison is None:
        return _unavailable(
            "compare_runs",
            "No baseline is selected, so there is nothing to compare this run against.",
        )

    metrics = [m for m in ctx.comparison["metrics"] if m["comparable"]]
    if not metrics:
        return _unavailable(
            "compare_runs",
            (
                f"{ctx.baseline_name} and {ctx.scenario_name} cannot be compared on any "
                "metric: no Delivery Amount was due at one of the two snapshots."
            ),
        )

    return Evidence(
        tool="compare_runs",
        status="ANSWERED",
        title=f"{ctx.baseline_name} → {ctx.scenario_name}",
        text=(
            "Both sides are full deterministic runs at pinned snapshots. Every delta "
            "is Decimal subtraction of two engine-computed figures, done server-side."
        ),
        fields=tuple(
            GuideField(
                label=str(metric["label"]),
                value=f"{_money(metric['before'])} → {_money(metric['after'])}",
                headline=metric["id"] == "call_amount",
            )
            for metric in metrics
        )
        + tuple(
            GuideField(label=f"Δ {metric['label']}", value=_money(metric["delta"]))
            for metric in metrics
            if metric["delta"] is not None
        ),
        source="Workflow & Impact",
        href="/workflow",
        paths=tuple(f"comparison.metrics[{metric['id']}]" for metric in metrics),
    )


def _tool_allocation_reasons(ctx: GuideContext, args: JSON) -> Evidence:
    if not ctx.may("view:desk"):
        return _refuse("get_allocation_reasons", "view:desk")

    include = str(args.get("include", "all"))
    allocation = ctx.run["allocation"]
    if allocation["status"] == "NOT_REQUIRED":
        return _unavailable(
            "get_allocation_reasons",
            "The optimiser was not invoked at this snapshot, so nothing was selected "
            "or rejected. There are no reasons to give.",
        )

    fields: list[GuideField] = []
    paths: list[str] = []

    if include in {"selected", "all"}:
        for line in allocation["lines"]:
            if not line["selected"]:
                continue
            fields.append(
                GuideField(
                    label=str(line["description"]),
                    value=(
                        f"{_money(line['market_value_posted'])} posted · "
                        f"{line['effective_percentage']} after haircut · "
                        f"{line['cost_per_effective_unit_bps']} bps per effective unit"
                    ),
                )
            )
            paths.append(f"allocation.lines[{line['asset_id']}]")

    if include in {"excluded", "all"}:
        for line in allocation["considered"]:
            if line["selected"] or not line["not_selected_reason"]:
                continue
            fields.append(
                GuideField(
                    label=f"Not used — {line['description']}",
                    value=str(line["not_selected_reason"]),
                )
            )
            paths.append(f"allocation.considered[{line['asset_id']}].not_selected_reason")
        for item in allocation["excluded"]:
            fields.append(
                GuideField(
                    label=f"Ineligible — {item['asset_id']}",
                    value=str(item["reason"]),
                )
            )
            paths.append(f"allocation.excluded[{item['asset_id']}]")

    if not fields:
        return _unavailable(
            "get_allocation_reasons",
            f"The optimiser recorded no '{include}' lines for this run.",
        )

    binding = [p["name"] for p in allocation["shadow_prices"] if p["binding"]]
    text = (
        "The optimiser ranks by cost per effective unit — funding spread over "
        "post-haircut value — and takes the cheapest that satisfies every constraint."
    )
    if binding:
        text += f" Binding constraints on this run: {', '.join(binding)}."

    return Evidence(
        tool="get_allocation_reasons",
        status="ANSWERED",
        title="Why these assets",
        text=text,
        fields=tuple(fields),
        source="Optimisation",
        href="/optimisation",
        paths=tuple(paths),
    )


def _tool_role_capabilities(ctx: GuideContext, args: JSON) -> Evidence:
    if ctx.role is None:
        return _unavailable("get_role_capabilities", "You are not signed in.")

    mandate, cannot = ROLE_MANDATES.get(ctx.role, ("", ""))
    granted = sorted(ctx.permissions)
    return Evidence(
        tool="get_role_capabilities",
        status="ANSWERED",
        title=f"What {ctx.role} may do",
        text=f"{mandate} {cannot}",
        fields=(
            *(GuideField(label=PERMISSION_LABELS.get(p, p), value=p) for p in granted),
            GuideField(
                label="Screens reachable",
                value=str(len(screens_for(ctx.permissions))),
            ),
        ),
        source="Access control",
    )


def _workflow_position(ctx: GuideContext) -> int:
    """Where this run actually sits in the workflow.

    Read from the run rather than from anything the user said, so the answer to
    "what next?" is a fact about the state of the desk.

    Note what does *not* send a user back to step 0: terms served from the committed
    fixture. Those genuinely govern the run, so treating an unfrozen agreement as
    unfinished business would tell every visitor to go and review a contract that
    has nothing outstanding on it. Only fields actually awaiting a reviewer do that.
    """
    if ctx.pending_review > 0:
        return 0

    decision = ctx.run["decision"]
    if decision["requires_human_approval"] and not ctx.run.get("approval"):
        return 3
    if ctx.run.get("approval"):
        return 4
    return 1


def _tool_next_step(ctx: GuideContext, args: JSON) -> Evidence:
    if not ctx.may("view:desk"):
        return _refuse("next_step", "view:desk")

    index = _workflow_position(ctx)
    step = WORKFLOW[index]
    screen = screen_by_id(step.screen_id)
    assert screen is not None, "WORKFLOW references a screen id not in SCREENS"

    reachable = ctx.may(screen.permission)
    if reachable:
        text = f"{step.goal} Done when: {step.done_when}"
        href: str | None = screen.route
    else:
        holders = ", ".join(roles_holding(screen.permission))
        text = (
            f"{step.goal} That step happens on {screen.label}, which your role cannot "
            f"reach. It belongs to: {holders}."
        )
        href = None

    fields = [
        GuideField("Next", screen.label, headline=True),
        GuideField("Step", f"{step.index + 1} of {len(WORKFLOW)}"),
    ]
    if reachable:
        fields.append(GuideField("Route", screen.route))
    if ctx.pending_review:
        fields.append(GuideField("Clauses awaiting review", str(ctx.pending_review)))

    return Evidence(
        tool="next_step",
        status="ANSWERED",
        title="What to do next",
        text=text,
        fields=tuple(fields),
        source=screen.label,
        href=href,
        paths=("terms_source", "decision.requires_human_approval", "approval"),
    )


@dataclass(frozen=True)
class GuideTool:
    name: str
    description: str
    schema: JSON
    run: Callable[[GuideContext, JSON], Evidence]

    def spec(self) -> JSON:
        """The Anthropic tool definition.

        ``strict`` is set so the model's arguments are validated against the schema
        before they reach a tool. A malformed topic name should fail at the boundary,
        not inside a lookup.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
            "strict": True,
        }


def _schema(properties: JSON) -> JSON:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TOOLS: tuple[GuideTool, ...] = (
    GuideTool(
        name="list_screens",
        description=(
            "List every screen the signed-in role can reach, with its route. Call this "
            "before naming any screen or route."
        ),
        schema=_schema({}),
        run=_tool_list_screens,
    ),
    GuideTool(
        name="describe_screen",
        description=(
            "What one screen is for, what it displays, and what can be done on it. "
            "Use it to explain where something lives or how to perform an action."
        ),
        schema=_schema(
            {
                "screen_id": {
                    "type": "string",
                    "enum": [s.id for s in SCREENS],
                    "description": "The screen to describe.",
                }
            }
        ),
        run=_tool_describe_screen,
    ),
    GuideTool(
        name="get_run_figures",
        description=(
            "Engine-computed figures for the run currently on screen, by topic. This "
            "is the ONLY source of numbers. It retrieves; it never calculates."
        ),
        schema=_schema(
            {
                "topic": {
                    "type": "string",
                    "enum": list(_TOPICS),
                    "description": "Which part of the run to read.",
                }
            }
        ),
        run=_tool_get_run_figures,
    ),
    GuideTool(
        name="compare_runs",
        description=(
            "What changed between the baseline scenario and the current one. Deltas "
            "are computed server-side in Decimal — use this instead of subtracting."
        ),
        schema=_schema({}),
        run=_tool_compare_runs,
    ),
    GuideTool(
        name="get_allocation_reasons",
        description=(
            "Why the optimiser selected each posted asset, and why the others were "
            "rejected or ineligible."
        ),
        schema=_schema(
            {
                "include": {
                    "type": "string",
                    "enum": ["selected", "excluded", "all"],
                    "description": "Which side of the allocation to explain.",
                }
            }
        ),
        run=_tool_allocation_reasons,
    ),
    GuideTool(
        name="get_role_capabilities",
        description=(
            "What the signed-in role may and may not do, and which role holds a "
            "permission it lacks."
        ),
        schema=_schema({}),
        run=_tool_role_capabilities,
    ),
    GuideTool(
        name="next_step",
        description=(
            "Where this run sits in the desk workflow and what the user should do "
            "next. Read from run state, not inferred. Prefer it over guessing."
        ),
        schema=_schema({}),
        run=_tool_next_step,
    ),
)

_TOOLS_BY_NAME: dict[str, GuideTool] = {tool.name: tool for tool in TOOLS}


def execute(name: str, args: JSON, ctx: GuideContext) -> Evidence:
    """Run one tool. Unknown names produce evidence, never an exception."""
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        known = ", ".join(_TOOLS_BY_NAME)
        return _unavailable(name, f"There is no tool called '{name}'. Available: {known}.")
    return tool.run(ctx, args)


# ------------------------------------------------------------------- routing


@dataclass(frozen=True)
class Route:
    """A keyword path to a tool call.

    This is what answers in replay mode, and what answers when a live reply fails
    verification. Every route lands on the same tools the model uses, so the two
    paths cannot report different figures.
    """

    keywords: tuple[tuple[str, ...], ...]
    tool: str
    args: JSON = field(default_factory=dict)
    #: Offered to the user as a suggestion chip.
    example: str = ""
    permission: str = "view:desk"


ROUTES: tuple[Route, ...] = (
    Route(
        keywords=(
            ("what", "next"),
            ("what", "do", "now"),
            ("where", "do", "i", "start"),
            ("where", "start"),
            ("next", "step"),
        ),
        tool="next_step",
        example="What should I do next?",
    ),
    Route(
        keywords=(
            ("collateral", "requirement"),
            ("how", "much", "post"),
            ("call", "amount"),
            ("margin", "call"),
        ),
        tool="get_run_figures",
        args={"topic": "margin_call"},
        example="What is the current collateral requirement?",
    ),
    Route(
        keywords=(("exposure",), ("mark", "market"), ("mtm",), ("netting",)),
        tool="get_run_figures",
        args={"topic": "exposure"},
        example="What is the current exposure?",
    ),
    Route(
        keywords=(("threshold",), ("breach",)),
        tool="get_run_figures",
        args={"topic": "threshold"},
        example="Is the threshold breached?",
    ),
    Route(
        keywords=(("initial", "margin"), ("im",)),
        tool="get_run_figures",
        args={"topic": "initial_margin"},
        example="What is the initial margin?",
    ),
    Route(
        keywords=(
            ("what", "changed"),
            ("compare",),
            ("before", "after"),
            ("difference",),
            ("impact",),
        ),
        tool="compare_runs",
        example="What changed after the market movement?",
    ),
    Route(
        keywords=(
            ("why", "selected"),
            ("why", "chosen"),
            ("why", "this", "collateral"),
            ("cheapest",),
        ),
        tool="get_allocation_reasons",
        args={"include": "selected"},
        example="Why was this collateral selected?",
    ),
    Route(
        keywords=(("why", "not"), ("excluded",), ("rejected",), ("ineligible",)),
        tool="get_allocation_reasons",
        args={"include": "excluded"},
        example="Why was an asset excluded?",
    ),
    Route(
        keywords=(("allocation",), ("optimis",), ("optimiz",), ("saving",), ("posted",)),
        tool="get_run_figures",
        args={"topic": "allocation"},
        example="What did the optimiser save?",
    ),
    Route(
        keywords=(("decision",), ("approve",), ("happens", "next"), ("sign", "off")),
        tool="get_run_figures",
        args={"topic": "decision"},
        example="What is the decision, and who approves it?",
    ),
    Route(
        keywords=(("audit",), ("hash", "chain"), ("verified",)),
        tool="get_run_figures",
        args={"topic": "audit"},
        example="Is the audit chain verified?",
        permission="view:audit",
    ),
    Route(
        keywords=(("terms",), ("csa",), ("contract",), ("extract",), ("clause",)),
        tool="get_run_figures",
        args={"topic": "agreement"},
        example="Which agreement governs this run?",
        permission="view:contract",
    ),
    Route(
        keywords=(("real", "data"), ("simulated",), ("provenance",), ("snapshot",), ("reproduc",)),
        tool="get_run_figures",
        args={"topic": "provenance"},
        example="Is this real market data?",
    ),
    Route(
        keywords=(
            ("where", "do", "i"),
            ("where", "find"),
            ("where", "is"),
            ("which", "screen"),
            ("what", "screen"),
            ("screen",),
            ("page",),
            ("navigate",),
        ),
        tool="list_screens",
        example="Where do I find the audit trail?",
    ),
    Route(
        keywords=(("my", "role"), ("permission",), ("allowed",), ("can", "i")),
        tool="get_role_capabilities",
        example="What can my role do?",
    ),
)


def _normalise(question: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", question.lower())


def _score(question: str, candidate: Route) -> int:
    """Score a question against a route.

    A keyword group scores only when *every* term in it appears, so "why not used"
    does not also fire the "why selected" route on the word "why" alone. Longer
    groups score higher, which lets a specific phrasing beat a general one.
    """
    text = f" {_normalise(question)} "
    best = 0
    for group in candidate.keywords:
        if all(term in text for term in group):
            best = max(best, len(group) * 10 + sum(len(term) for term in group))
    return best


def _screen_named(question: str) -> Screen | None:
    """The screen a question names, if it names one.

    Longest label wins, so "audit trail" resolves to Audit Trail rather than to any
    screen whose shorter label also happens to appear in the sentence.
    """
    text = f" {_normalise(question)} "
    best: Screen | None = None
    for screen in SCREENS:
        label = _normalise(screen.label)
        if label in text and (best is None or len(label) > len(_normalise(best.label))):
            best = screen
    return best


def route(question: str, ctx: GuideContext) -> Route | None:
    """The best-matching route for this question, or ``None`` if nothing matches."""
    ranked = sorted(
        ((candidate, _score(question, candidate)) for candidate in ROUTES),
        key=lambda pair: pair[1],
        reverse=True,
    )
    for candidate, weight in ranked:
        if weight > 0:
            return candidate
    return None


def starters(ctx: GuideContext, limit: int = 6) -> tuple[str, ...]:
    """Suggested opening questions, filtered to what this role can actually be told."""
    return tuple(
        candidate.example
        for candidate in ROUTES
        if candidate.example and ctx.may(candidate.permission)
    )[:limit]


# --------------------------------------------------------------- the guard


#: What counts as a figure for verification purposes: money, decimals carrying cents,
#: percentages and basis points. Deliberately *not* bare small integers — a paragraph
#: reference, a step count or a year is not a financial claim, and flagging those
#: would make the guard fire on correct answers.
#: Each pattern is anchored so it cannot match *inside* a longer number. Without
#: the guards, "USD 12,500,000.00" also yields the substring "000.00", which no tool
#: ever returned — and the guard would then reject every correct answer it saw.
_EDGE = r"(?<![\d,])(?<!\d\.)"
_END = r"(?![\d,])(?!\.\d)"

_FIGURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(_EDGE + r"\d{1,3}(?:,\d{3})+(?:\.\d+)?" + _END),
    re.compile(_EDGE + r"\d+\.\d{2,}" + _END),
    re.compile(r"(?:USD|EUR|GBP|JPY|INR|SGD|CHF|AUD|CAD)\s*(-?[\d,]+(?:\.\d+)?)" + _END),
    re.compile(_EDGE + r"(-?\d+(?:\.\d+)?)\s*(?:%|bps)", re.IGNORECASE),
)

_ANY_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _to_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _figures_in(text: str) -> list[Decimal]:
    found: list[Decimal] = []
    for pattern in _FIGURE_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(1) if match.groups() else match.group(0)
            value = _to_decimal(token)
            if value is not None:
                found.append(value)
    return found


def _permitted_figures(evidence: tuple[Evidence, ...], question: str) -> set[Decimal]:
    """Every figure the model was actually shown, plus the ones the user supplied.

    A percentage may be quoted either as ``0.08`` or as ``8``, and the engine emits
    both conventions in different places, so each value is admitted in both scales.
    The guard exists to catch invented figures, not to arbitrate rounding.
    """
    permitted: set[Decimal] = set()
    sources = [question]
    for item in evidence:
        sources.append(item.text)
        sources.extend(f.value for f in item.fields)

    for text in sources:
        for match in _ANY_NUMBER.finditer(text):
            value = _to_decimal(match.group(0))
            if value is None:
                continue
            permitted.add(value)
            permitted.add(value * 100)
            permitted.add(value / 100)
    return permitted


def stray_figures(reply: str, evidence: tuple[Evidence, ...], question: str) -> tuple[str, ...]:
    """Figures in the prose that no tool result supports.

    This is the last gate before a user reads a number. It runs on every live answer,
    and a non-empty result discards that answer entirely rather than editing it: a
    reply containing one invented figure is not a reply to be repaired.
    """
    permitted = _permitted_figures(evidence, question)
    # A figure can match more than one pattern — "USD 7,500,000.00" matches both the
    # separator form and the currency form — so report each distinct value once.
    stray = {str(value) for value in _figures_in(reply) if value not in permitted}
    return tuple(sorted(stray))


# ------------------------------------------------------------- composition


def _actions(evidence: tuple[Evidence, ...]) -> tuple[tuple[str, str], ...]:
    seen: dict[str, str] = {}
    for item in evidence:
        if item.href and item.href not in seen:
            seen[item.href] = f"Open {item.source}"
    return tuple((label, href) for href, label in seen.items())


def _follow_ups(ctx: GuideContext, asked: str) -> tuple[str, ...]:
    normalised = _normalise(asked)
    return tuple(
        candidate.example
        for candidate in ROUTES
        if candidate.example
        and ctx.may(candidate.permission)
        and _normalise(candidate.example) != normalised
    )[:3]


def _unknown(ctx: GuideContext, guard: str = "OK") -> GuideAnswer:
    offered = starters(ctx, limit=4)
    return GuideAnswer(
        status="UNKNOWN",
        reply=(
            "I do not hold an answer to that. I read figures out of the run on screen "
            "and I know what each screen of this application is for — I do not "
            "calculate, and I do not answer from outside this run. Try one of these."
        ),
        follow_ups=offered,
        guard=guard,
    )


def _compose(question: str, evidence: tuple[Evidence, ...], ctx: GuideContext) -> GuideAnswer:
    """Build an answer from evidence without a model.

    Used in replay mode and whenever a live answer is rejected. The prose is the
    engine's own wording plus a pointer to the screen showing the same figures, which
    is exactly as much as can be said without composing anything.
    """
    if not evidence:
        return _unknown(ctx)

    primary = evidence[0]
    if primary.status != "ANSWERED":
        return GuideAnswer(
            status=primary.status,
            reply=primary.text,
            evidence=evidence,
            follow_ups=_follow_ups(ctx, question),
        )

    sentences = [primary.text]
    if primary.href:
        sentences.append(f"{primary.source} ({primary.href}) shows the same figures in context.")

    return GuideAnswer(
        status="ANSWERED",
        reply=" ".join(sentences),
        evidence=evidence,
        actions=_actions(evidence),
        follow_ups=_follow_ups(ctx, question),
    )


def _answer_deterministic(question: str, ctx: GuideContext) -> GuideAnswer:
    matched = route(question, ctx)
    if matched is None:
        return _unknown(ctx)
    if not ctx.may(matched.permission):
        return GuideAnswer(
            status="NOT_PERMITTED",
            reply=_refuse(matched.tool, matched.permission).text,
            follow_ups=_follow_ups(ctx, question),
        )

    tool, args = matched.tool, matched.args

    # "Where do I find the audit trail?" names a screen. Listing all eleven would be
    # a worse answer than describing the one asked about.
    if tool == "list_screens":
        named = _screen_named(question)
        if named is not None:
            tool, args = "describe_screen", {"screen_id": named.id}

    evidence: tuple[Evidence, ...] = (execute(tool, args, ctx),)

    # A guide answers "and then what?" without being asked again. The next step is
    # appended to anything that is not already the next step.
    if tool != "next_step" and ctx.may("view:desk"):
        evidence = (*evidence, execute("next_step", {}, ctx))

    return _compose(question, evidence, ctx)


# ------------------------------------------------------------------ the agent


def _session_brief(ctx: GuideContext) -> str:
    """Facts about this session, appended to the prompt.

    Deliberately carries no figures. The model is told *what* it is looking at and
    must call a tool to learn any number about it.
    """
    return (
        "\n\n# This session\n"
        f"Signed in as: {ctx.role or 'nobody'}.\n"
        f"Scenario on screen: {ctx.scenario_name}.\n"
        f"Baseline for comparison: {ctx.baseline_name}.\n"
        f"Valuation date: {ctx.run['as_of']}. Snapshot: {ctx.run['snapshot']['snapshot_id']}.\n"
        f"Clauses awaiting review: {ctx.pending_review}.\n"
        "You have not been told any figure from this run. Call a tool for every one."
    )


def _answer_live(
    question: str,
    history: tuple[tuple[str, str], ...],
    ctx: GuideContext,
    settings: Settings,
) -> GuideAnswer:
    """One turn of the agent loop.

    A manual loop rather than the SDK's tool runner: every tool result is captured as
    :class:`Evidence` on the way past, because the user is shown the same objects the
    model was given.
    """
    install_tls_trust(settings)

    from anthropic import Anthropic
    from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam

    client = Anthropic(api_key=settings.api_key)

    messages: list[MessageParam] = [
        {"role": "assistant" if speaker == "assistant" else "user", "content": content}
        for speaker, content in history
    ]
    messages.append({"role": "user", "content": question})

    # `strict` is part of the tool definition, so the model's arguments are validated
    # against the schema before any tool here sees them.
    tools: list[ToolParam] = [cast("ToolParam", tool.spec()) for tool in TOOLS]

    evidence: list[Evidence] = []
    tool_calls = 0

    for _ in range(MAX_TOOL_TURNS):
        # No `temperature`: sampling parameters are rejected on this model family.
        # Determinism here comes from the tools, not from the decoder.
        response = client.messages.create(
            model=settings.model_id,
            max_tokens=MAX_REPLY_TOKENS,
            system=GUIDE_PROMPT + _session_brief(ctx),
            tools=tools,
            output_config={"effort": "low"},
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            reply = "".join(
                block.text for block in response.content if block.type == "text"
            ).strip()
            return _finish(
                question,
                reply,
                tuple(evidence),
                ctx,
                settings=settings,
                tool_calls=tool_calls,
            )

        messages.append({"role": "assistant", "content": cast("Any", response.content)})
        results: list[ToolResultBlockParam] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls += 1
            arguments = block.input if isinstance(block.input, dict) else {}
            found = execute(block.name, arguments, ctx)
            evidence.append(found)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": found.as_json(),
                }
            )
        messages.append({"role": "user", "content": results})

    # The loop was cut. Whatever was retrieved is still true, so it is served.
    return _compose(question, tuple(evidence), ctx)


def _finish(
    question: str,
    reply: str,
    evidence: tuple[Evidence, ...],
    ctx: GuideContext,
    *,
    settings: Settings,
    tool_calls: int,
) -> GuideAnswer:
    """Verify a model reply, then accept it or discard it."""
    if not reply:
        return _compose(question, evidence, ctx)

    stray = stray_figures(reply, evidence, question)
    if stray:
        fallback = _compose(question, evidence, ctx)
        return GuideAnswer(
            status=fallback.status,
            reply=fallback.reply,
            evidence=fallback.evidence,
            actions=fallback.actions,
            follow_ups=fallback.follow_ups,
            route="deterministic",
            guard="FIGURE_NOT_IN_EVIDENCE",
            model_id=settings.model_id,
            tool_calls=tool_calls,
        )

    refused = any(item.status == "NOT_PERMITTED" for item in evidence)
    answered = any(item.status == "ANSWERED" for item in evidence)
    status = "ANSWERED" if answered else ("NOT_PERMITTED" if refused else "UNAVAILABLE")

    return GuideAnswer(
        status=status,
        reply=reply,
        evidence=evidence,
        actions=_actions(evidence),
        follow_ups=_follow_ups(ctx, question),
        route="model",
        guard="OK",
        model_id=settings.model_id,
        tool_calls=tool_calls,
    )


def answer(
    question: str,
    ctx: GuideContext,
    settings: Settings,
    history: tuple[tuple[str, str], ...] = (),
) -> GuideAnswer:
    """Answer one question.

    Live mode runs the agent; replay mode runs the keyword router. A live failure —
    no key, no network, an SDK error — degrades to the router rather than to an
    error, because an assistant that stops working when the network does is not one
    a demo can rely on.
    """
    if not question.strip():
        return _unknown(ctx)

    if settings.mode is not Mode.LIVE:
        return _answer_deterministic(question, ctx)

    if not settings.api_key:
        fallback = _answer_deterministic(question, ctx)
        return GuideAnswer(
            status=fallback.status,
            reply=fallback.reply,
            evidence=fallback.evidence,
            actions=fallback.actions,
            follow_ups=fallback.follow_ups,
            guard="MODEL_UNAVAILABLE",
        )

    try:
        return _answer_live(question, history, ctx, settings)
    except Exception:
        # Any SDK or transport failure degrades to the router. The assistant never
        # returns a 500 to a user who asked a question.
        fallback = _answer_deterministic(question, ctx)
        return GuideAnswer(
            status=fallback.status,
            reply=fallback.reply,
            evidence=fallback.evidence,
            actions=fallback.actions,
            follow_ups=fallback.follow_ups,
            guard="MODEL_ERROR",
            model_id=settings.model_id,
        )
