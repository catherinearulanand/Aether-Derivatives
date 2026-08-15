"""Audit chain, decision record, and end-to-end pipeline.

The determinism test in this module *is* the reproducibility claim. Without it,
"reproducible" is marketing.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from aether.core.audit import GENESIS_HASH, ActorType, AuditChain, canonical_json
from aether.core.decision import DecisionAction, DecisionStatus
from aether.core.money import Currency, Money
from aether.core.optimize import OptimizerStatus
from aether.pipeline import run_scenario

USD = Currency.USD
BASE_DATE = date(2026, 8, 14)
STRESS_DATE = date(2026, 8, 17)


@pytest.fixture(scope="module")
def stress_run():
    return run_scenario("MKT-2026-08-17-STRESS", STRESS_DATE)


@pytest.fixture(scope="module")
def base_run():
    return run_scenario("MKT-2026-08-14-BASE", BASE_DATE)


# ---------------------------------------------------------------- audit


class TestCanonicalJson:
    def test_key_order_does_not_change_the_encoding(self):
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_money_encodes_without_precision_loss(self):
        encoded = canonical_json({"v": Money.of("1234567.89", USD)})
        assert '"amount":"1234567.89"' in encoded
        assert '"currency":"USD"' in encoded

    def test_floats_are_refused(self):
        """A float's repr is not stable enough to hash."""
        with pytest.raises(TypeError, match="float"):
            canonical_json({"v": 1.5})


class TestAuditChain:
    def _chain(self) -> AuditChain:
        chain = AuditChain(chain_id="T")
        for i in range(3):
            chain = chain.append(
                actor="test",
                actor_type=ActorType.ENGINE,
                action=f"STEP_{i}",
                entity_type="thing",
                entity_id=str(i),
                occurred_at="2026-08-17",
                payload={"i": i},
            )
        return chain

    def test_starts_from_genesis(self):
        assert AuditChain(chain_id="T").head_hash == GENESIS_HASH

    def test_links_each_event_to_its_predecessor(self):
        chain = self._chain()
        assert chain.events[0].prev_hash == GENESIS_HASH
        for earlier, later in zip(chain.events, chain.events[1:], strict=False):
            assert later.prev_hash == earlier.hash

    def test_a_clean_chain_verifies(self):
        valid, break_at, message = self._chain().verify()
        assert valid
        assert break_at is None
        assert "verify" in message

    def test_tampering_with_a_payload_is_detected(self):
        chain = self._chain()
        tampered = replace(chain.events[1], payload={"i": 999})
        broken = AuditChain(
            chain_id="T",
            events=(chain.events[0], tampered, chain.events[2]),
        )

        valid, break_at, message = broken.verify()
        assert not valid
        assert break_at == 1
        assert "altered" in message

    def test_reordering_is_detected(self):
        chain = self._chain()
        broken = AuditChain(
            chain_id="T",
            events=(chain.events[0], chain.events[2], chain.events[1]),
        )
        valid, break_at, _ = broken.verify()
        assert not valid
        assert break_at == 1

    def test_append_returns_a_new_chain(self):
        original = self._chain()
        extended = original.append(
            actor="t",
            actor_type=ActorType.HUMAN,
            action="X",
            entity_type="y",
            entity_id="z",
            occurred_at="2026-08-17",
        )
        assert len(original) == 3
        assert len(extended) == 4


# ------------------------------------------------------------- pipeline


class TestStressRun:
    """The demo path: a rate shock produces a call that must be collateralised."""

    def test_completes_and_verifies(self, stress_run):
        assert stress_run.audit_verified

    def test_produces_a_delivery_decision(self, stress_run):
        decision = stress_run.decision
        assert decision.action is DecisionAction.POST_COLLATERAL
        assert decision.status is DecisionStatus.PENDING_APPROVAL
        assert decision.amount == Money.of("9500000", USD)

    def test_never_executes_autonomously(self, stress_run):
        """The system proposes. A human disposes."""
        assert stress_run.decision.requires_human_approval
        assert "No financial transaction is executed" in stress_run.decision.disclaimer

    def test_allocation_beats_the_baseline(self, stress_run):
        allocation = stress_run.allocation
        assert allocation is not None
        assert allocation.status is OptimizerStatus.OPTIMAL
        assert allocation.total_cost < allocation.baseline_cost

    def test_rationale_explains_the_binding_constraint(self, stress_run):
        joined = " ".join(stress_run.decision.rationale)
        assert "Binding constraint" in joined
        assert "Excluded US0000C2Y09" in joined

    def test_records_every_stage_in_the_audit_chain(self, stress_run):
        actions = [event.action for event in stress_run.audit.events]
        assert actions == [
            "RUN_STARTED",
            "TOOL_CALLED",
            "EXPOSURE_COMPUTED",
            "TOOL_CALLED",
            "RISK_SENSITIVITIES_MEASURED",
            "TOOL_CALLED",
            "INITIAL_MARGIN_COMPUTED",
            "TOOL_CALLED",
            "MARGIN_CALL_COMPUTED",
            "TOOL_CALLED",
            "COLLATERAL_OPTIMISED",
            "TOOL_CALLED",
            "SETTLEMENT_INSTRUCTION_GENERATED",
            "DECISION_RECORDED",
            "RUN_COMPLETED",
        ]

    def test_every_engine_computation_is_preceded_by_an_agent_tool_call(self, stress_run):
        """The product's central claim, asserted against the audit trail itself.

        Every number-bearing ENGINE event must sit immediately behind an AGENT event
        that decided to ask for it. If an engine result ever appears without an agent
        having requested it, the orchestration story is decoration.
        """
        events = stress_run.audit.events
        computed = [
            (index, event)
            for index, event in enumerate(events)
            if event.actor_type is ActorType.ENGINE and event.action.endswith(("ED", "GENERATED"))
        ]
        assert computed, "No engine computations were recorded at all."

        for index, event in computed:
            if event.action == "DECISION_RECORDED":
                continue  # assembled from results already computed, not a tool call
            previous = events[index - 1]
            assert previous.actor_type is ActorType.AGENT, (
                f"{event.action} at index {index} was not requested by an agent; "
                f"it follows {previous.actor_type.value} {previous.action}."
            )

    def test_agent_events_carry_no_monetary_values(self, stress_run):
        """An agent passes references. It cannot pass a number that becomes cash.

        Enforced at construction by ``ToolCall``; asserted here against what actually
        reached the audit trail, because that is the artifact a judge or an auditor
        would read.
        """
        for event in stress_run.audit.events:
            if event.actor_type is not ActorType.AGENT:
                continue
            for name, value in event.payload.get("arguments", {}).items():
                assert isinstance(value, str | int | type(None)), (
                    f"Agent tool call carried {name}={value!r} of type {type(value).__name__}."
                )

    def test_audit_distinguishes_engine_from_system(self, stress_run):
        engine_actions = {
            e.action for e in stress_run.audit.events if e.actor_type is ActorType.ENGINE
        }
        assert "MARGIN_CALL_COMPUTED" in engine_actions
        assert "COLLATERAL_OPTIMISED" in engine_actions

    def test_initial_margin_is_reported_but_not_charged(self, stress_run):
        """IM is indicative. Folding it into a VM call would overstate the requirement."""
        assert stress_run.initial_margin.initial_margin.is_positive
        assert stress_run.margin_call.initial_margin.is_zero


class TestBaseRun:
    """The control case: the Threshold gate demonstrably gates."""

    def test_generates_no_call(self, base_run):
        assert not base_run.margin_call.has_call
        assert base_run.decision.action is DecisionAction.NO_ACTION
        assert base_run.decision.status is DecisionStatus.NO_ACTION_REQUIRED

    def test_needs_no_approval(self, base_run):
        assert not base_run.decision.requires_human_approval

    def test_skips_optimisation(self, base_run):
        assert base_run.allocation is None

    def test_still_writes_a_verifiable_audit_chain(self, base_run):
        assert base_run.audit_verified
        assert "COLLATERAL_OPTIMISED" not in [e.action for e in base_run.audit.events]


class TestDeterminism:
    """This test is the reproducibility claim."""

    @pytest.mark.determinism
    def test_two_runs_produce_identical_audit_hashes(self):
        first = run_scenario("MKT-2026-08-17-STRESS", STRESS_DATE)
        second = run_scenario("MKT-2026-08-17-STRESS", STRESS_DATE)

        assert first.audit.head_hash == second.audit.head_hash
        assert [e.hash for e in first.audit.events] == [e.hash for e in second.audit.events]

    @pytest.mark.determinism
    def test_two_runs_produce_identical_figures(self):
        first = run_scenario("MKT-2026-08-17-STRESS", STRESS_DATE)
        second = run_scenario("MKT-2026-08-17-STRESS", STRESS_DATE)

        assert first.exposure.exposure == second.exposure.exposure
        assert first.margin_call.call_amount == second.margin_call.call_amount
        assert first.allocation is not None and second.allocation is not None
        assert first.allocation.total_cost == second.allocation.total_cost

    @pytest.mark.determinism
    def test_different_snapshots_produce_different_hashes(self):
        """Sanity: the hash must actually depend on the inputs."""
        stress = run_scenario("MKT-2026-08-17-STRESS", STRESS_DATE)
        base = run_scenario("MKT-2026-08-14-BASE", BASE_DATE)
        assert stress.audit.head_hash != base.audit.head_hash


class TestSnapshotPinning:
    def test_mismatched_valuation_date_is_refused(self):
        with pytest.raises(ValueError, match="must match the pinned snapshot"):
            run_scenario("MKT-2026-08-17-STRESS", BASE_DATE)


class TestOverCollateralised:
    def test_excess_collateral_produces_a_recall(self):
        """Opening balance far above the requirement on the quiet snapshot."""
        run = run_scenario("MKT-2026-08-14-BASE", BASE_DATE, posted_value=Money.of("5000000", USD))
        assert run.decision.action is DecisionAction.RECALL_COLLATERAL
        assert run.decision.amount.is_positive
        assert run.allocation is None
