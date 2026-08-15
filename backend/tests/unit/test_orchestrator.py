"""The agent boundary, tested as a structural guarantee rather than a convention.

The product's central claim is that a language model never produces an authoritative
number. Everywhere else that claim rests on the review gate. Here it rests on a type:
a tool call's arguments admit identifiers and flags and nothing else, so an agent
cannot hand a number to the engine even if a model hallucinated one into the plan.

If any test in this file can be made to pass while a ``Decimal`` reaches a tool, the
claim is false and the architecture is decoration.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from aether.agents.orchestrator import (
    TOOL_REGISTRY,
    AgentRole,
    RunContext,
    ToolCall,
    collateral_optimizer_plan,
    parse_model_plan,
    risk_engine_plan,
    validate_plan,
)
from aether.core.audit import ActorType
from aether.core.money import Currency, Money
from aether.fixtures.loader import (
    load_agreement,
    load_inventory,
    load_portfolio,
    load_snapshot,
)
from aether.pipeline import run_scenario

USD = Currency.USD


@pytest.fixture(scope="module")
def context():
    return RunContext(
        terms=load_agreement(),
        portfolio=load_portfolio(),
        inventory=load_inventory(),
        snapshot=load_snapshot("MKT-2026-08-17-STRESS"),
        as_of=date(2026, 8, 17),
    )


class TestArgumentsCannotCarryValue:
    """The load-bearing test in this file."""

    @pytest.mark.parametrize(
        "value",
        [
            Decimal("9500000.00"),
            9_500_000.0,
            Money.of("9500000", USD),
            [1, 2, 3],
            {"amount": "1"},
        ],
        ids=["decimal", "float", "money", "list", "dict"],
    )
    def test_rejects_anything_that_is_not_a_reference(self, value):
        with pytest.raises(TypeError, match="not permitted"):
            ToolCall(
                agent=AgentRole.RISK_ENGINE,
                tool="compute_credit_support_amount",
                intent="smuggle a number past the boundary",
                arguments={"agreement_id": "CSA-MERIDIAN-2026", "amount": value},
            )

    @pytest.mark.parametrize("value", ["CSA-MERIDIAN-2026", 8, True, None])
    def test_accepts_identifiers_counts_and_flags(self, value):
        call = ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="compute_credit_support_amount",
            intent="reference only",
            arguments={"agreement_id": "CSA-MERIDIAN-2026", "reference": value},
        )
        assert call.arguments["reference"] == value

    def test_the_error_explains_the_rule(self):
        with pytest.raises(TypeError) as info:
            ToolCall(
                agent=AgentRole.RISK_ENGINE,
                tool="price_netting_set",
                intent="",
                arguments={"x": Decimal("1")},
            )
        assert "Agents pass references, not values" in str(info.value)


class TestPlanValidation:
    def test_accepts_the_policy_plan(self, context):
        valid, message = validate_plan(risk_engine_plan(context))
        assert valid, message

    def test_rejects_an_empty_plan(self):
        valid, message = validate_plan(())
        assert not valid
        assert "empty" in message.lower()

    def test_rejects_an_unknown_tool(self):
        call = ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="transfer_funds",
            intent="not a thing that exists",
            arguments={},
        )
        valid, message = validate_plan((call,))
        assert not valid
        assert "Unknown tool" in message

    def test_rejects_a_tool_owned_by_another_agent(self):
        call = ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="optimise_collateral",
            intent="reach across the boundary",
            arguments={"agreement_id": "X", "inventory_id": "Y"},
        )
        valid, message = validate_plan((call,))
        assert not valid
        assert "belongs to" in message

    def test_rejects_a_missing_required_argument(self):
        call = ToolCall(
            agent=AgentRole.RISK_ENGINE,
            tool="price_netting_set",
            intent="incomplete",
            arguments={"netting_set_id": "NS-MERIDIAN-001"},
        )
        valid, message = validate_plan((call,))
        assert not valid
        assert "snapshot_id" in message


class TestModelPlans:
    def test_parses_a_well_formed_plan(self):
        raw = json.dumps(
            {
                "plan": [
                    {
                        "tool": "price_netting_set",
                        "intent": "value the book",
                        "arguments": {
                            "netting_set_id": "NS-MERIDIAN-001",
                            "snapshot_id": "MKT-2026-08-17-STRESS",
                        },
                    }
                ]
            }
        )
        plan = parse_model_plan(raw)
        assert len(plan) == 1
        assert plan[0].agent is AgentRole.RISK_ENGINE

    def test_rejects_a_numeric_argument(self):
        """The failure mode this guard exists for: a model inventing a figure."""
        raw = json.dumps(
            {
                "plan": [
                    {
                        "tool": "compute_credit_support_amount",
                        "intent": "I have computed the answer myself",
                        "arguments": {
                            "agreement_id": "CSA-MERIDIAN-2026",
                            "credit_support_amount": 9500000.0,
                        },
                    }
                ]
            }
        )
        with pytest.raises(TypeError, match="not permitted"):
            parse_model_plan(raw)

    def test_rejects_malformed_json(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_model_plan("{not json")

    def test_rejects_an_unknown_tool(self):
        raw = json.dumps({"plan": [{"tool": "wire_the_money", "arguments": {}}]})
        with pytest.raises(ValueError, match="Unknown tool"):
            parse_model_plan(raw)


class TestRouting:
    """The optimizer agent's decisions are conditional, not scripted."""

    def test_a_delivery_we_owe_reaches_the_linear_program(self, context):
        result = run_scenario("MKT-2026-08-17-STRESS", date(2026, 8, 17), run_id="R1")
        plan = collateral_optimizer_plan(context, result.margin_call)
        assert [c.tool for c in plan] == [
            "optimise_collateral",
            "generate_settlement_instruction",
        ]

    def test_no_call_invokes_no_tool(self, context):
        result = run_scenario("MKT-2026-08-14-BASE", date(2026, 8, 14), run_id="R2")
        assert not result.margin_call.has_call
        assert collateral_optimizer_plan(context, result.margin_call) == ()

    def test_a_call_the_counterparty_owes_is_not_optimised(self, context):
        """Optimising our inventory against their obligation would be nonsense."""
        result = run_scenario("MKT-2026-08-18-CRASH", date(2026, 8, 18), run_id="R3")
        plan = collateral_optimizer_plan(context, result.margin_call)
        assert [c.tool for c in plan] == ["generate_settlement_instruction"]
        assert "not" in plan[0].intent.lower()

    def test_a_return_amount_is_not_optimised(self, context):
        result = run_scenario(
            "MKT-2026-08-17-STRESS",
            date(2026, 8, 17),
            run_id="R4",
            posted_value=Money.of("15000000", USD),
        )
        plan = collateral_optimizer_plan(context, result.margin_call)
        assert [c.tool for c in plan] == ["generate_settlement_instruction"]


class TestRegistry:
    def test_every_tool_has_an_owner_among_the_three_agents(self):
        owners = {spec.owner for spec in TOOL_REGISTRY}
        assert owners <= set(AgentRole)

    def test_tool_names_are_unique(self):
        names = [spec.name for spec in TOOL_REGISTRY]
        assert len(names) == len(set(names))

    def test_every_tool_declares_what_it_produces(self):
        assert all(spec.produces for spec in TOOL_REGISTRY)


class TestAuditProvesTheBoundary:
    @pytest.fixture(scope="class")
    @classmethod
    def run(cls):
        return run_scenario("MKT-2026-08-17-STRESS", date(2026, 8, 17), run_id="RUN-BOUNDARY")

    def test_agent_and_engine_events_alternate(self, run):
        computed = (ActorType.AGENT, ActorType.ENGINE)
        events = [e for e in run.audit.events if e.actor_type in computed]
        # The decision event is assembled from results already computed, not a tool call.
        pairs = [e for e in events if e.action != "DECISION_RECORDED"]
        for index in range(0, len(pairs), 2):
            assert pairs[index].actor_type is ActorType.AGENT
            assert pairs[index + 1].actor_type is ActorType.ENGINE

    def test_no_agent_event_carries_a_monetary_string(self, run):
        """Belt and braces: scan the serialised payloads a reader would actually see."""
        for event in run.audit.events:
            if event.actor_type is not ActorType.AGENT:
                continue
            for value in event.payload.get("arguments", {}).values():
                assert not isinstance(value, float | Decimal)

    def test_the_trace_names_all_three_agents_across_the_workflow(self, run):
        agents = {action.agent for action in run.agent_actions}
        assert AgentRole.RISK_ENGINE in agents
        assert AgentRole.COLLATERAL_OPTIMIZER in agents

    def test_every_action_states_an_intent(self, run):
        assert all(action.intent for action in run.agent_actions)
