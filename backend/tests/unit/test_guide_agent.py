"""Contract tests for the guide agent.

The assistant is the one surface where a model writes prose a user reads next to
money. These tests assert the four things that makes safe, in the order they matter:

1. **It answers with no network.** Replay is the demo path; the assistant must work
   there completely, not degrade to an apology.
2. **Its figures are the run's figures.** Every value the assistant reports is
   asserted equal to the field the dashboard renders, not merely "present".
3. **Permission is a gate, not a request.** A role that may not see a screen gets a
   refusal from the tool, regardless of what any prompt says.
4. **An invented figure is discarded.** The guard is tested with a reply that would
   look entirely plausible to a reader, which is exactly the failure it exists for.

The registry tests additionally pin the backend's screen and role tables against the
frontend's, because an assistant that confidently routes a user to a screen that no
longer exists is worse than one that says it does not know.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aether.agents.guide import (
    MAX_TOOL_TURNS,
    ROUTES,
    TOOLS,
    Evidence,
    GuideContext,
    GuideField,
    _finish,
    answer,
    execute,
    route,
    starters,
    stray_figures,
)
from aether.agents.screens import SCREENS, WORKFLOW, screen_by_id
from aether.api.main import SCENARIOS, _approvals, _execute, _run_payload
from aether.api.serializers import serialise_comparison
from aether.config import Mode, Settings
from aether.roles import ROLE_PERMISSIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "frontend" / "src" / "lib"


@pytest.fixture
def run() -> dict:
    """A real pipeline run — the same payload the dashboard renders."""
    _approvals.clear()
    payload = _run_payload("stress")
    _approvals.clear()
    return payload


@pytest.fixture
def comparison() -> dict:
    """The baseline-to-current deltas, as the app supplies them."""
    before, _, _ = _execute("base")
    after, _, _ = _execute("stress")
    return serialise_comparison(before, after, dict(SCENARIOS["base"]), dict(SCENARIOS["stress"]))


@pytest.fixture
def ctx(run: dict, comparison: dict) -> GuideContext:
    return GuideContext(
        run=run,
        comparison=comparison,
        role="RISK",
        scenario_name="Rate shock",
        baseline_name="Quiet market",
    )


@pytest.fixture
def replay() -> Settings:
    return Settings(mode=Mode.REPLAY)


# ------------------------------------------------------- the demo path


class TestReplayAnswers:
    """Replay is the demo path. It must answer, not degrade."""

    def test_answers_without_a_model(self, ctx: GuideContext, replay: Settings) -> None:
        result = answer("What is the current collateral requirement?", ctx, replay)

        assert result.status == "ANSWERED"
        assert result.route == "deterministic"
        assert result.model_id is None
        assert result.evidence

    def test_replay_never_imports_the_sdk(
        self, ctx: GuideContext, replay: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A network call on the demo path would be a defect, so make one impossible."""
        import builtins

        real_import = builtins.__import__

        def refuse(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("anthropic"):
                raise AssertionError("replay mode must not import the model SDK")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", refuse)
        result = answer("What is the exposure?", ctx, replay)
        assert result.status == "ANSWERED"

    def test_every_suggestion_is_answerable(self, ctx: GuideContext, replay: Settings) -> None:
        """A chip the assistant then fails to answer is a broken promise."""
        offered = starters(ctx)
        assert offered

        for question in offered:
            result = answer(question, ctx, replay)
            assert result.status == "ANSWERED", f"{question!r} produced {result.status}"

    def test_no_baseline_is_stated_not_guessed(self, run: dict, replay: Settings) -> None:
        """With nothing to compare against, say so — do not answer from one side."""
        alone = GuideContext(
            run=run,
            comparison=None,
            role="RISK",
            scenario_name="Rate shock",
            baseline_name="Rate shock",
        )
        result = answer("What changed after the market movement?", alone, replay)

        assert result.status == "UNAVAILABLE"
        assert "nothing to compare" in result.reply

    def test_an_unrecognised_question_says_so(self, ctx: GuideContext, replay: Settings) -> None:
        result = answer("Who is the counterparty's credit analyst?", ctx, replay)

        assert result.status == "UNKNOWN"
        assert not result.evidence
        assert result.follow_ups


# ------------------------------------------------------- figures are the run's


class TestFiguresComeFromTheEngine:
    def test_margin_figures_equal_the_run(self, ctx: GuideContext, run: dict) -> None:
        evidence = execute("get_run_figures", {"topic": "margin_call"}, ctx)
        call = run["margin_call"]
        by_label = {f.label: f.value for f in evidence.fields}

        assert evidence.status == "ANSWERED"
        assert by_label["Call amount"] == (
            f"{call['call_amount']['currency']} {call['call_amount']['amount']}"
        )
        assert by_label["Threshold"] == (
            f"{call['threshold']['currency']} {call['threshold']['amount']}"
        )
        assert evidence.text == call["summary"]

    def test_exposure_figures_equal_the_run(self, ctx: GuideContext, run: dict) -> None:
        evidence = execute("get_run_figures", {"topic": "exposure"}, ctx)
        by_label = {f.label: f.value for f in evidence.fields}
        exposure = run["exposure"]["exposure"]

        assert by_label["Exposure"] == f"{exposure['currency']} {exposure['amount']}"
        assert by_label["Trades"] == str(run["exposure"]["trade_count"])

    def test_paths_name_real_fields(self, ctx: GuideContext, run: dict) -> None:
        """Every path offered to a sceptic must resolve in the payload it cites."""
        evidence = execute("get_run_figures", {"topic": "exposure"}, ctx)

        for path in evidence.paths:
            node: object = run
            for part in path.split("."):
                assert isinstance(node, dict), f"{path} does not resolve"
                assert part in node, f"{path} does not resolve: no '{part}'"
                node = node[part]

    def test_no_tool_computes(self, ctx: GuideContext) -> None:
        """A tool may select and format. If one ever subtracts, this catches it."""
        source = Path(__file__).resolve().parents[2] / "aether" / "agents" / "guide.py"
        body = source.read_text(encoding="utf-8")
        tools_section = body.split(
            "# --------------------------------------------------------------------- tools"
        )[1]
        tools_section = tools_section.split(
            "# ------------------------------------------------------------------- routing"
        )[0]

        assert "Decimal(" not in tools_section, "a tool is parsing money into arithmetic"


# ------------------------------------------------------------- permissions


class TestPermissionIsAGate:
    def test_unsigned_visitor_is_refused(self, run: dict) -> None:
        anonymous = GuideContext(
            run=run, comparison=None, role=None, scenario_name="x", baseline_name="y"
        )
        evidence = execute("get_run_figures", {"topic": "margin_call"}, anonymous)

        assert evidence.status == "NOT_PERMITTED"
        assert not evidence.fields

    def test_auditor_cannot_reach_admin(self, run: dict) -> None:
        auditor = GuideContext(
            run=run, comparison=None, role="AUDITOR", scenario_name="x", baseline_name="y"
        )
        evidence = execute("describe_screen", {"screen_id": "admin"}, auditor)

        assert evidence.status == "NOT_PERMITTED"
        assert "ADMIN" in evidence.text

    def test_refusal_names_who_can(self, run: dict) -> None:
        auditor = GuideContext(
            run=run, comparison=None, role="AUDITOR", scenario_name="x", baseline_name="y"
        )
        evidence = execute("describe_screen", {"screen_id": "reconciliation"}, auditor)

        assert evidence.status == "NOT_PERMITTED"
        assert "RISK" in evidence.text and "ADMIN" in evidence.text

    def test_suggestions_are_filtered_by_role(self, run: dict) -> None:
        anonymous = GuideContext(
            run=run, comparison=None, role=None, scenario_name="x", baseline_name="y"
        )
        assert starters(anonymous) == ()


# ------------------------------------------------------------- the guard


CALL = Evidence(
    tool="get_run_figures",
    status="ANSWERED",
    title="Margin call",
    text="A Delivery Amount is due.",
    fields=(
        GuideField("Call amount", "USD 12500000.00", headline=True),
        GuideField("Threshold", "USD 5000000.00"),
        GuideField("Saving", "18.40%"),
    ),
    source="Exposure & Margin",
    href="/exposure",
)


class TestFigureGuard:
    def test_figures_from_evidence_pass(self) -> None:
        reply = (
            "A Delivery Amount of USD 12,500,000.00 is due against a USD 5,000,000.00 Threshold."
        )
        assert stray_figures(reply, (CALL,), "what is due?") == ()

    def test_an_invented_figure_is_caught(self) -> None:
        reply = (
            "A Delivery Amount of USD 12,500,000.00 is due, leaving USD 7,500,000.00 of headroom."
        )
        assert stray_figures(reply, (CALL,), "what is due?") == ("7500000.00",)

    def test_arithmetic_is_caught(self) -> None:
        """The subtraction is correct. It is still not permitted."""
        reply = "The call exceeds the Threshold by USD 7,500,000.00."
        assert stray_figures(reply, (CALL,), "how much over?") != ()

    def test_percentages_pass_in_either_scale(self) -> None:
        assert stray_figures("It saved 18.40%.", (CALL,), "") == ()
        assert stray_figures("A saving of 0.1840 of the baseline.", (CALL,), "") == ()

    def test_clause_and_step_references_are_not_figures(self) -> None:
        """Paragraph 2(c), 3 assets, a 2016 form — none of these is a financial claim."""
        reply = "Paragraph 2(c) applies. 3 assets were posted under the 2016 form."
        assert stray_figures(reply, (CALL,), "") == ()

    def test_a_figure_the_user_supplied_passes(self) -> None:
        reply = "No, the Threshold is not USD 9,000,000.00."
        assert stray_figures(reply, (CALL,), "is the threshold USD 9,000,000.00?") == ()

    def test_the_whole_reply_is_discarded(self, ctx: GuideContext, replay: Settings) -> None:
        """One bad figure voids the answer. It is not edited and not apologised for."""
        bad = "A Delivery Amount of USD 12,500,000.00 is due, leaving USD 7,500,000.00 spare."
        result = _finish(
            "what is due?",
            bad,
            (CALL,),
            ctx,
            settings=replay,
            tool_calls=1,
        )

        assert result.guard == "FIGURE_NOT_IN_EVIDENCE"
        assert result.route == "deterministic"
        assert "7,500,000.00" not in result.reply
        assert result.evidence == (CALL,)

    def test_a_clean_reply_is_kept(self, ctx: GuideContext, replay: Settings) -> None:
        good = "A Delivery Amount of USD 12,500,000.00 is due. Open Exposure & Margin."
        result = _finish("what is due?", good, (CALL,), ctx, settings=replay, tool_calls=1)

        assert result.guard == "OK"
        assert result.route == "model"
        assert result.reply == good


# ------------------------------------------------------------- guidance


class TestGuidance:
    def test_next_step_reads_run_state(self, ctx: GuideContext) -> None:
        evidence = execute("next_step", {}, ctx)
        by_label = {f.label: f.value for f in evidence.fields}

        assert evidence.status == "ANSWERED"
        assert by_label["Next"] in {s.label for s in SCREENS}
        assert evidence.href in {s.route for s in SCREENS}

    def test_unreviewed_terms_send_you_to_contracts(self, run: dict) -> None:
        pending = GuideContext(
            run=run,
            comparison=None,
            role="LEGAL",
            scenario_name="x",
            baseline_name="y",
            pending_review=3,
        )
        evidence = execute("next_step", {}, pending)
        by_label = {f.label: f.value for f in evidence.fields}

        assert by_label["Next"] == "Contracts"
        assert by_label["Clauses awaiting review"] == "3"

    def test_an_answer_carries_the_next_step(self, ctx: GuideContext, replay: Settings) -> None:
        """A guide volunteers what to do next; it should not have to be asked twice."""
        result = answer("What is the current exposure?", ctx, replay)

        assert [e.tool for e in result.evidence][-1] == "next_step"
        assert result.actions

    def test_a_named_screen_is_described_not_listed(
        self, ctx: GuideContext, replay: Settings
    ) -> None:
        """Asking where one screen is should not return a directory of eleven."""
        result = answer("Where do I find the audit trail?", ctx, replay)
        first = result.evidence[0]

        assert result.status == "ANSWERED"
        assert first.tool == "describe_screen"
        assert first.href == "/audit"
        assert ("Open Audit Trail", "/audit") in result.actions

    def test_an_unnamed_navigation_question_lists_screens(
        self, ctx: GuideContext, replay: Settings
    ) -> None:
        result = answer("Which screens can I reach?", ctx, replay)
        routes = {s.route for s in SCREENS}

        assert result.status == "ANSWERED"
        assert result.evidence[0].tool == "list_screens"
        for guide_field in result.evidence[0].fields:
            assert guide_field.value in routes

    def test_every_route_named_is_a_real_route(self, ctx: GuideContext, replay: Settings) -> None:
        """Across every suggestion, the assistant may only point at screens that exist."""
        routes = {s.route for s in SCREENS}

        for question in starters(ctx):
            result = answer(question, ctx, replay)
            for _, href in result.actions:
                assert href in routes, f"{question!r} pointed at {href}"


# ------------------------------------------------------------- registries


class TestRegistries:
    def test_every_route_targets_a_real_tool(self) -> None:
        names = {tool.name for tool in TOOLS}
        for candidate in ROUTES:
            assert candidate.tool in names

    def test_every_route_argument_is_in_the_schema(self) -> None:
        by_name = {tool.name: tool for tool in TOOLS}
        for candidate in ROUTES:
            schema = by_name[candidate.tool].schema["properties"]
            for key, value in candidate.args.items():
                assert key in schema, f"{candidate.tool} has no argument '{key}'"
                assert value in schema[key]["enum"]

    def test_workflow_references_real_screens(self) -> None:
        for step in WORKFLOW:
            assert screen_by_id(step.screen_id) is not None

    def test_screens_match_the_frontend_navigation(self) -> None:
        """The assistant may not route a user to a screen the app does not have."""
        source = (REPO_ROOT / "frontend" / "src" / "components" / "Shell.tsx").read_text(
            encoding="utf-8"
        )
        nav = re.findall(
            r'href:\s*"([^"]+)",\s*label:\s*"([^"]+)",\s*hint:\s*"[^"]*",'
            r'\s*permission:\s*"([^"]+)"',
            source,
            re.DOTALL,
        )
        assert nav, "could not parse the navigation out of Shell.tsx"

        backend = {s.route: (s.label, s.permission) for s in SCREENS if s.in_nav}
        frontend = {route: (label, permission) for route, label, permission in nav}

        assert backend == frontend

    def test_roles_match_the_frontend(self) -> None:
        """A permission model that disagrees across the wire is worse than none."""
        source = (FRONTEND / "roles.ts").read_text(encoding="utf-8")

        parsed: dict[str, set[str]] = {}
        for role in ROLE_PERMISSIONS:
            block = re.search(rf"{role}:\s*{{.*?permissions:\s*\[(.*?)\]", source, re.DOTALL)
            assert block, f"could not find {role} in roles.ts"
            parsed[role] = set(re.findall(r'"([^"]+)"', block.group(1)))

        assert parsed == {role: set(perms) for role, perms in ROLE_PERMISSIONS.items()}


# ------------------------------------------------------------- the endpoint


class TestEndpoint:
    def test_chat_carries_provenance(self) -> None:
        from fastapi.testclient import TestClient

        from aether.api.main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/assistant/chat",
                json={
                    "question": "What is the current collateral requirement?",
                    "scenario_key": "stress",
                    "baseline_key": "base",
                    "role": "RISK",
                },
            )

        assert response.status_code == 200
        body = response.json()

        # The reproducibility contract: this payload carries engine figures.
        for key in ("engine_version", "snapshot_id", "as_of", "trace_id"):
            assert body[key], f"missing {key}"

        assert body["status"] == "ANSWERED"
        assert body["evidence"]
        assert body["guard"] == "OK"

    def test_chat_rejects_an_unknown_scenario(self) -> None:
        from fastapi.testclient import TestClient

        from aether.api.main import app

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/assistant/chat",
                json={"question": "hello", "scenario_key": "nope", "role": "RISK"},
            )

        assert response.status_code == 404

    def test_suggestions_respect_the_role(self) -> None:
        from fastapi.testclient import TestClient

        from aether.api.main import app

        with TestClient(app) as client:
            signed_in = client.get("/api/v1/assistant/suggestions", params={"role": "RISK"})
            anonymous = client.get("/api/v1/assistant/suggestions")

        assert signed_in.json()["suggestions"]
        assert anonymous.json()["suggestions"] == []


def test_route_prefers_the_more_specific_phrasing(ctx: GuideContext) -> None:
    """'why was it not used' must not fire the 'why selected' route on 'why'."""
    selected = route("Why was this collateral selected?", ctx)
    excluded = route("Why was that asset not used?", ctx)

    assert selected is not None and selected.args == {"include": "selected"}
    assert excluded is not None and excluded.args == {"include": "excluded"}


# ------------------------------------------------------------- the live path


class _Block:
    """One content block, shaped like the SDK's."""

    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)


class _Response:
    def __init__(self, stop_reason: str, content: list[_Block]) -> None:
        self.stop_reason = stop_reason
        self.content = content


class _Messages:
    """A scripted model. Each call returns the next queued response."""

    def __init__(self, script: list[_Response]) -> None:
        self._script = script
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> _Response:
        self.calls.append(dict(kwargs))
        return self._script.pop(0)


class _Client:
    def __init__(self, script: list[_Response]) -> None:
        self.messages = _Messages(script)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-a-real-credential")
    return Settings(mode=Mode.LIVE)


def _install(monkeypatch: pytest.MonkeyPatch, script: list[_Response]) -> _Client:
    client = _Client(script)
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: client)
    return client


class TestLivePath:
    def test_the_tool_loop_runs_and_the_reply_is_kept(
        self, ctx: GuideContext, live: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The agent calls a tool, then answers from what it returned."""
        call = ctx.run["margin_call"]["call_amount"]
        script = [
            _Response(
                "tool_use",
                [
                    _Block(
                        type="tool_use",
                        id="tu_1",
                        name="get_run_figures",
                        input={"topic": "margin_call"},
                    )
                ],
            ),
            _Response(
                "end_turn",
                [
                    _Block(
                        type="text",
                        text=(
                            f"A Delivery Amount of {call['currency']} {call['amount']} "
                            "is due. Open Exposure & Margin (/exposure)."
                        ),
                    )
                ],
            ),
        ]
        client = _install(monkeypatch, script)

        result = answer("How much do we have to post?", ctx, live)

        assert result.route == "model"
        assert result.guard == "OK"
        assert result.tool_calls == 1
        assert result.model_id == live.model_id
        assert [e.tool for e in result.evidence] == ["get_run_figures"]

        # The request must not carry a sampling parameter: they are rejected on this
        # model family, and determinism here comes from the tools regardless.
        first = client.messages.calls[0]
        assert "temperature" not in first
        assert first["model"] == live.model_id
        assert {tool["name"] for tool in first["tools"]} == {t.name for t in TOOLS}

    def test_an_invented_figure_discards_the_live_answer(
        self, ctx: GuideContext, live: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure this whole design exists to prevent, end to end."""
        script = [
            _Response(
                "tool_use",
                [
                    _Block(
                        type="tool_use",
                        id="tu_1",
                        name="get_run_figures",
                        input={"topic": "margin_call"},
                    )
                ],
            ),
            _Response(
                "end_turn",
                [_Block(type="text", text="You have USD 123,456,789.00 of headroom.")],
            ),
        ]
        _install(monkeypatch, script)

        result = answer("How much headroom is there?", ctx, live)

        assert result.guard == "FIGURE_NOT_IN_EVIDENCE"
        assert result.route == "deterministic"
        assert "123,456,789.00" not in result.reply
        # The evidence survives: the tool result was true, only the prose was not.
        assert [e.tool for e in result.evidence] == ["get_run_figures"]

    def test_a_refused_tool_is_not_worked_around(
        self, run: dict, live: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that asks for contract terms without the permission gets nothing."""
        anonymous = GuideContext(
            run=run, comparison=None, role=None, scenario_name="x", baseline_name="y"
        )
        script = [
            _Response(
                "tool_use",
                [
                    _Block(
                        type="tool_use",
                        id="tu_1",
                        name="get_run_figures",
                        input={"topic": "agreement"},
                    )
                ],
            ),
            _Response("end_turn", [_Block(type="text", text="I cannot show you that.")]),
        ]
        _install(monkeypatch, script)

        result = answer("What is the Threshold?", anonymous, live)

        assert result.evidence[0].status == "NOT_PERMITTED"
        assert not result.evidence[0].fields

    def test_a_transport_failure_degrades_to_the_router(
        self, ctx: GuideContext, live: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An assistant that stops working when the network does is not usable."""
        import anthropic

        def explode(**_: object) -> None:
            raise ConnectionError("TLS handshake failed")

        monkeypatch.setattr(anthropic, "Anthropic", explode)

        result = answer("What is the current exposure?", ctx, live)

        assert result.guard == "MODEL_ERROR"
        assert result.status == "ANSWERED"
        assert result.evidence

    def test_live_without_a_key_degrades(
        self, ctx: GuideContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = answer("What is the current exposure?", ctx, Settings(mode=Mode.LIVE))

        assert result.guard == "MODEL_UNAVAILABLE"
        assert result.status == "ANSWERED"

    def test_a_runaway_loop_is_cut(
        self, ctx: GuideContext, live: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model that never stops calling tools still produces an answer."""
        tool_turn = _Response(
            "tool_use",
            [
                _Block(
                    type="tool_use",
                    id="tu",
                    name="get_run_figures",
                    input={"topic": "exposure"},
                )
            ],
        )
        _install(monkeypatch, [tool_turn for _ in range(MAX_TOOL_TURNS)])

        result = answer("What is the exposure?", ctx, live)

        assert result.status == "ANSWERED"
        assert result.route == "deterministic"
        assert result.evidence
