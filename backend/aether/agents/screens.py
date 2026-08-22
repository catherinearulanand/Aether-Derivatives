"""The interface map, as data.

The assistant guides a user through the application by **reading this table**, not by
recalling what the UI looks like. That matters for the same reason the rest of the
system is built the way it is: a model asked "where do I approve this?" will happily
invent a plausible route. Here it cannot — it may only name a screen that exists in
this registry, and the registry is asserted against the frontend's navigation by test.

Two things live here:

:data:`SCREENS`
    Every screen, what it answers, what it shows, what can be done on it, and the
    permission needed to reach it.

:data:`WORKFLOW`
    The order a user should walk them in. The navigation is already ordered as the
    pipeline runs — contract, exposure, margin, optimisation, decision, audit — and
    this encodes that sequence so the assistant can answer "what do I do next?" with
    a position rather than a guess.

Pure data. No I/O, no framework, no model.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SCREENS", "WORKFLOW", "Screen", "WorkflowStep", "screen_by_id", "screens_for"]


@dataclass(frozen=True)
class Screen:
    """One screen of the application."""

    id: str
    route: str
    label: str
    #: The permission a role needs to reach it. Mirrors the navigation bar.
    permission: str
    #: The question this screen exists to answer, in one line.
    purpose: str
    #: What is displayed on it.
    shows: tuple[str, ...]
    #: What a user can actually do here. Empty when the screen is read-only.
    actions: tuple[str, ...]
    #: True when the screen appears in the main navigation bar. The rest are
    #: reachable from the footer or from a link on another screen.
    in_nav: bool


SCREENS: tuple[Screen, ...] = (
    Screen(
        id="dashboard",
        route="/",
        label="Dashboard",
        permission="view:desk",
        purpose="The margin desk: what happened, what changed, and what to post.",
        shows=(
            "Headline decision and the amount called",
            "Before/after against the baseline scenario",
            "The allocation the optimiser chose",
            "Agent swarm summary",
        ),
        actions=("Switch the current and baseline scenario", "Approve the decision"),
        in_nav=True,
    ),
    Screen(
        id="workflow",
        route="/workflow",
        label="Workflow & Impact",
        permission="view:desk",
        purpose="Every pipeline stage opened up: its input, its output, and what it changed.",
        shows=(
            "Stage-by-stage progression from CSA to decision",
            "What each stage received and produced",
            "Where a human decision altered the result",
        ),
        actions=(),
        in_nav=True,
    ),
    Screen(
        id="review",
        route="/review",
        label="Contracts",
        permission="view:contract",
        purpose="What the Legal-Clause Agent extracted from the CSA, and the review gate.",
        shows=(
            "Extracted terms with page, clause and verbatim citation",
            "Per-field confidence and review flags",
            "Which fields are waiting on a human decision",
        ),
        actions=(
            "Confirm or correct a flagged clause",
            "Freeze the agreement so the engine computes on the reviewed version",
        ),
        in_nav=True,
    ),
    Screen(
        id="exposure",
        route="/exposure",
        label="Exposure & Margin",
        permission="view:desk",
        purpose="Mark-to-market, the CSA margin waterfall, and initial margin.",
        shows=(
            "Trade-level valuations and the netting benefit",
            "The waterfall from exposure to call amount, with the clause behind each step",
            "Threshold and Minimum Transfer Amount gates",
            "Schedule-based initial margin",
        ),
        actions=(),
        in_nav=True,
    ),
    Screen(
        id="optimisation",
        route="/optimisation",
        label="Optimisation",
        permission="view:desk",
        purpose="Which assets may be posted, which were chosen, and what that saved.",
        shows=(
            "Eligibility and haircuts per asset",
            "The linear program's allocation and its cost",
            "Cash-first baseline and the saving against it",
            "Binding constraints as shadow prices",
        ),
        actions=(),
        in_nav=True,
    ),
    Screen(
        id="analytics",
        route="/analytics",
        label="Analytics",
        permission="view:desk",
        purpose="Concentration, funding cost, and what the market event did.",
        shows=(
            "Concentration of the posted portfolio",
            "Cost breakdown by asset class",
            "The before/after effect of the market movement",
        ),
        actions=(),
        in_nav=True,
    ),
    Screen(
        id="reconciliation",
        route="/reconciliation",
        label="Reconciliation",
        permission="act:reconcile",
        purpose="Internal collateral ledger against the custodian statement.",
        shows=("Matched positions", "Breaks, with the side that disagrees"),
        actions=("Upload a ledger and run a reconciliation",),
        in_nav=True,
    ),
    Screen(
        id="audit",
        route="/audit",
        label="Audit Trail",
        permission="view:audit",
        purpose="The hash chain from agent to engine to human, and its verification.",
        shows=(
            "Every recorded event with actor, action and hash",
            "Chain verification status and where it breaks if it does",
        ),
        actions=("Export the trail",),
        in_nav=True,
    ),
    Screen(
        id="admin",
        route="/admin",
        label="Admin",
        permission="view:admin",
        purpose="Workflow status board and system state.",
        shows=("Progress across the desk", "Mode, engine version and system health"),
        actions=(),
        in_nav=True,
    ),
    Screen(
        id="agents",
        route="/agents",
        label="Agents",
        permission="view:desk",
        purpose="Which agent decided what, and what it was allowed to hand the engine.",
        shows=(
            "Each agent action and its typed output",
            "The boundary between what an agent interpreted and what the engine computed",
        ),
        actions=(),
        in_nav=False,
    ),
    Screen(
        id="settlement",
        route="/settlement",
        label="Settlement",
        permission="view:desk",
        purpose="The settlement instruction the decision would produce.",
        shows=(
            "A SWIFT-shaped MT527 message and its ISO 20022 equivalent",
            "An explicit statement that nothing is transmitted",
        ),
        actions=(),
        in_nav=False,
    ),
    Screen(
        id="methodology",
        route="/methodology",
        label="Methodology",
        permission="view:desk",
        purpose="What is modelled, what is not, and what may never be claimed.",
        shows=(
            "Each engine's method and its stated limits",
            "The measured extraction evaluation score",
            "Simulated-data provenance",
        ),
        actions=(),
        in_nav=False,
    ),
)


@dataclass(frozen=True)
class WorkflowStep:
    """One position in the order a user should walk the application."""

    index: int
    screen_id: str
    #: What the user is trying to establish at this point.
    goal: str
    #: How they know this step is done.
    done_when: str


#: The pipeline order. Walking the navigation top to bottom walks the pipeline, and
#: this makes that sequence addressable so "what next?" has a determinate answer.
WORKFLOW: tuple[WorkflowStep, ...] = (
    WorkflowStep(
        index=0,
        screen_id="review",
        goal="Establish which contractual terms govern this run.",
        done_when="Every flagged clause is confirmed and the agreement is frozen.",
    ),
    WorkflowStep(
        index=1,
        screen_id="exposure",
        goal="See the mark-to-market and how the CSA turns it into a requirement.",
        done_when="The waterfall from exposure to call amount reads end to end.",
    ),
    WorkflowStep(
        index=2,
        screen_id="optimisation",
        goal="See which assets were selected against that requirement, and why.",
        done_when="The allocation covers the requirement and the saving is understood.",
    ),
    WorkflowStep(
        index=3,
        screen_id="dashboard",
        goal="Take the decision on the amount and the allocation.",
        done_when="The decision is approved and recorded.",
    ),
    WorkflowStep(
        index=4,
        screen_id="audit",
        goal="Verify the chain from contract to decision.",
        done_when="The chain verifies and the head hash is recorded.",
    ),
)


def screen_by_id(screen_id: str) -> Screen | None:
    """The screen with this id, or ``None``. Never raises: the caller may be a model."""
    for screen in SCREENS:
        if screen.id == screen_id:
            return screen
    return None


def screens_for(permissions: frozenset[str]) -> tuple[Screen, ...]:
    """The screens a holder of these permissions can actually reach."""
    return tuple(screen for screen in SCREENS if screen.permission in permissions)
