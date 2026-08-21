"""Comparison and approval contract tests.

Two claims are asserted here, and both are load-bearing for the product's story:

1. A before/after comparison reports **exact** differences between two engine runs.
   Every delta is recomputed independently from the two sides' own figures, so a
   drifting subtraction cannot pass.
2. A human approval enters the tamper-evident chain as a ``HUMAN`` event, is refused
   for roles that may not sign, and does not break determinism — the approval is an
   input to the run, replayed from its recorded timestamp rather than a clock.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from aether.api.main import _approvals, app

APPROVAL = {
    "approver": "j.mehta@aether.example",
    "role": "RISK",
    "note": "Delivery Amount agrees with the counterparty's statement.",
    "occurred_at": "2026-08-17T16:40:00Z",
}


@pytest.fixture
def client():
    """A client over a clean approval store.

    Approvals are process state; a test that left one behind would change what a
    later test's chain contains.
    """
    _approvals.clear()
    yield TestClient(app)
    _approvals.clear()


def _amount(money: dict[str, str]) -> Decimal:
    return Decimal(money["amount"])


class TestComparison:
    def test_reports_both_snapshots(self, client):
        body = client.get("/api/v1/comparison/base/stress").json()

        assert body["before"]["snapshot_id"] == "MKT-2026-08-14-BASE"
        assert body["after"]["snapshot_id"] == "MKT-2026-08-17-STRESS"
        assert body["before"]["as_of"] == "2026-08-14"
        assert body["after"]["as_of"] == "2026-08-17"
        assert body["simulated"] is True

    def test_every_delta_is_exactly_after_minus_before(self, client):
        """The arithmetic, recomputed independently of the serialiser."""
        body = client.get("/api/v1/comparison/base/stress").json()

        comparable = [m for m in body["metrics"] if m["comparable"]]
        assert comparable, "Nothing was comparable, so nothing was asserted."

        for metric in comparable:
            expected = _amount(metric["after"]) - _amount(metric["before"])
            assert _amount(metric["delta"]) == expected, metric["id"]

    def test_direction_matches_the_sign_of_the_delta(self, client):
        body = client.get("/api/v1/comparison/base/stress").json()

        for metric in body["metrics"]:
            if not metric["comparable"]:
                assert metric["direction"] == "NOT_COMPARABLE"
                assert metric["delta"] is None
                continue
            delta = _amount(metric["delta"])
            expected = "UP" if delta > 0 else "DOWN" if delta < 0 else "FLAT"
            assert metric["direction"] == expected, metric["id"]

    def test_metrics_agree_with_the_runs_they_compare(self, client):
        """A comparison figure must equal the figure the run endpoint serves.

        This is the single-source-of-truth invariant. If the dashboard and the
        before/after view could disagree, the product's central claim is unfalsifiable.
        """
        comparison = client.get("/api/v1/comparison/base/stress").json()
        before = client.post("/api/v1/scenarios/base/run").json()
        after = client.post("/api/v1/scenarios/stress/run").json()

        by_id = {m["id"]: m for m in comparison["metrics"]}

        assert by_id["portfolio_mtm"]["before"] == before["exposure"]["exposure"]
        assert by_id["portfolio_mtm"]["after"] == after["exposure"]["exposure"]
        assert by_id["call_amount"]["after"] == after["margin_call"]["call_amount"]
        assert (
            by_id["credit_support_amount"]["after"] == after["margin_call"]["credit_support_amount"]
        )
        assert by_id["collateral_post_haircut"]["after"] == after["allocation"]["allocated_value"]

    def test_allocation_only_metrics_are_not_reported_as_zero(self, client):
        """No optimizer run means no figure — which is not a figure of zero."""
        body = client.get("/api/v1/comparison/base/stress").json()
        pool = next(m for m in body["metrics"] if m["id"] == "eligible_pool")

        assert pool["before_available"] is False
        assert pool["after_available"] is True
        assert pool["comparable"] is False
        assert pool["unavailable_reason"]

    def test_allocation_delta_classifies_each_asset(self, client):
        body = client.get("/api/v1/comparison/base/stress").json()
        rows = body["allocation_delta"]

        assert rows, "The stress run posts collateral, so rows are expected."
        assert all(r["status"] == "ADDED" for r in rows), (
            "Nothing was posted in the quiet market, so every line is new."
        )
        for row in rows:
            assert _amount(row["before"]) == Decimal("0.00")
            assert _amount(row["delta"]) == _amount(row["after"])

    def test_threshold_status_moves_from_within_to_breached(self, client):
        body = client.get("/api/v1/comparison/base/stress").json()

        assert body["before"]["threshold_status"]["state"] == "WITHIN"
        assert body["after"]["threshold_status"]["state"] == "BREACHED"

    def test_transferor_change_is_flagged(self, client):
        """The flash crash reverses who owes collateral, and that must be visible."""
        body = client.get("/api/v1/comparison/stress/crash").json()

        assert body["before"]["transferor"] == "PARTY_A"
        assert body["after"]["transferor"] == "PARTY_B"
        assert body["transferor_changed"] is True

    def test_refuses_to_run_backwards_in_time(self, client):
        response = client.get("/api/v1/comparison/stress/base")
        assert response.status_code == 422

    def test_unknown_scenario_is_a_404(self, client):
        assert client.get("/api/v1/comparison/base/nonesuch").status_code == 404


class TestApproval:
    def test_approval_appends_a_human_event_to_the_chain(self, client):
        before = client.post("/api/v1/scenarios/stress/run").json()
        body = client.post("/api/v1/scenarios/stress/approve", json=APPROVAL).json()

        assert len(body["audit"]["events"]) == len(before["audit"]["events"]) + 1

        event = body["audit"]["events"][-1]
        assert event["actor_type"] == "HUMAN"
        assert event["action"] == "DECISION_APPROVED"
        assert event["actor"] == APPROVAL["approver"]
        assert event["occurred_at"] == APPROVAL["occurred_at"]
        assert event["payload"]["role"] == "RISK"
        assert event["payload"]["authorises_transfer"] is False

    def test_the_chain_still_verifies_after_approval(self, client):
        body = client.post("/api/v1/scenarios/stress/approve", json=APPROVAL).json()

        assert body["audit"]["verified"] is True
        assert body["audit"]["break_at"] is None

    def test_approval_records_what_was_approved(self, client):
        run = client.post("/api/v1/scenarios/stress/run").json()
        body = client.post("/api/v1/scenarios/stress/approve", json=APPROVAL).json()

        approval = body["approval"]
        assert approval["decision_id"] == run["decision"]["decision_id"]
        assert approval["action_approved"] == run["decision"]["action"]
        assert approval["amount_approved"] == run["decision"]["amount"]["amount"]

    def test_approval_survives_a_re_run_and_stays_deterministic(self, client):
        """Two runs of an approved scenario hash identically.

        The approval carries its own recorded timestamp, so replaying it reads no
        clock and the determinism invariant is untouched.
        """
        client.post("/api/v1/scenarios/stress/approve", json=APPROVAL)

        first = client.post("/api/v1/scenarios/stress/run").json()
        second = client.post("/api/v1/scenarios/stress/run").json()

        assert first["audit"]["head_hash"] == second["audit"]["head_hash"]
        assert first["audit"]["events"][-1]["action"] == "DECISION_APPROVED"

    def test_an_unapproved_run_has_no_human_approval_event(self, client):
        body = client.post("/api/v1/scenarios/stress/run").json()

        actions = [e["action"] for e in body["audit"]["events"]]
        assert "DECISION_APPROVED" not in actions
        assert body["approval"] is None

    def test_an_approval_does_not_leak_onto_another_scenario(self, client):
        client.post("/api/v1/scenarios/stress/approve", json=APPROVAL)
        other = client.post("/api/v1/scenarios/crash/run").json()

        actions = [e["action"] for e in other["audit"]["events"]]
        assert "DECISION_APPROVED" not in actions

    @pytest.mark.parametrize("role", ["AUDITOR", "LEGAL", "GUEST"])
    def test_roles_that_may_not_sign_are_refused(self, client, role):
        response = client.post("/api/v1/scenarios/stress/approve", json={**APPROVAL, "role": role})
        assert response.status_code == 403

    def test_an_unnamed_approver_is_refused(self, client):
        response = client.post(
            "/api/v1/scenarios/stress/approve", json={**APPROVAL, "approver": "   "}
        )
        assert response.status_code == 422

    def test_a_decision_needing_no_approval_cannot_be_signed(self, client):
        """The quiet market produces NO_ACTION. There is nothing to approve."""
        response = client.post("/api/v1/scenarios/base/approve", json=APPROVAL)
        assert response.status_code == 409

    def test_revoking_removes_the_event(self, client):
        client.post("/api/v1/scenarios/stress/approve", json=APPROVAL)
        body = client.request("DELETE", "/api/v1/scenarios/stress/approve").json()

        actions = [e["action"] for e in body["audit"]["events"]]
        assert "DECISION_APPROVED" not in actions
        assert body["approval"] is None
        assert body["audit"]["verified"] is True


class TestThresholdStatus:
    @pytest.mark.parametrize(
        ("key", "state"),
        [("base", "WITHIN"), ("stress", "BREACHED"), ("crash", "BREACHED")],
    )
    def test_run_reports_its_threshold_state(self, client, key, state):
        body = client.post(f"/api/v1/scenarios/{key}/run").json()

        assert body["threshold_status"]["state"] == state
        assert body["threshold_status"]["message"]

    def test_threshold_state_agrees_with_the_margin_call(self, client):
        for key in ("base", "stress", "crash"):
            body = client.post(f"/api/v1/scenarios/{key}/run").json()
            status = body["threshold_status"]
            call = body["margin_call"]

            assert status["threshold"] == call["threshold"]
            assert status["call_amount"] == call["call_amount"]
            assert status["transferor"] == call["transferor"]

            exceeded = Decimal(call["credit_support_amount"]["amount"]) > 0
            assert (status["state"] == "WITHIN") is not exceeded
