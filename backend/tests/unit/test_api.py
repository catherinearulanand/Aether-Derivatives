"""API contract tests.

The contract invariant asserted here — every response carrying a computed number also
carries its provenance — is what makes reproducibility part of the interface rather
than a property we claim in a slide.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from aether.api.main import app

DOCUMENT_ID = "CSA-MERIDIAN-2026"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def stress(client):
    response = client.post("/api/v1/scenarios/stress/run")
    assert response.status_code == 200
    return response.json()


class TestMeta:
    def test_health_reports_the_mode(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["mode"] in {"replay", "live"}
        assert body["simulated_data"] is True

    def test_methodology_states_what_is_not_modelled(self, client):
        body = client.get("/api/v1/methodology").json()
        assert body["principle"].startswith("Language models extract")
        assert any("SIMM" in item for item in body["not_modelled"])
        assert "ISDA SIMM" in body["never_claimed"]
        assert body["all_data_simulated"] is True

    def test_openapi_schema_is_generated(self, client):
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "AETHER"
        assert "SIMULATED" in schema["info"]["description"]


class TestReproducibilityContract:
    """Every computed number carries the state that produced it."""

    def test_margin_call_carries_provenance(self, stress):
        call = stress["margin_call"]
        for key in ("engine_version", "snapshot_id", "as_of", "agreement_id"):
            assert call[key], f"margin call is missing {key}"

    def test_decision_carries_provenance(self, stress):
        decision = stress["decision"]
        for key in ("engine_version", "snapshot_id", "as_of", "decision_id"):
            assert decision[key]

    def test_exposure_carries_provenance(self, stress):
        exposure = stress["exposure"]
        assert exposure["snapshot_id"]
        assert exposure["as_of"]
        assert exposure["netting_set_id"]

    def test_money_is_a_string_never_a_float(self, stress):
        """A float round-trip through JavaScript would lose cents on a nine-figure trade."""
        amount = stress["margin_call"]["call_amount"]["amount"]
        assert isinstance(amount, str)
        assert Decimal(amount) == Decimal("9500000.00")

    def test_every_money_field_is_a_decimal_string(self, stress):
        def walk(node):
            if isinstance(node, dict):
                if set(node) == {"amount", "currency"}:
                    assert isinstance(node["amount"], str), node
                    Decimal(node["amount"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(stress)

    def test_two_identical_runs_return_identical_hashes(self, client):
        first = client.post("/api/v1/scenarios/stress/run").json()
        second = client.post("/api/v1/scenarios/stress/run").json()
        assert first["audit"]["head_hash"] == second["audit"]["head_hash"]


class TestScenarioRun:
    def test_stress_produces_a_call(self, stress):
        assert stress["margin_call"]["has_call"] is True
        assert stress["decision"]["action"] == "POST_COLLATERAL"

    def test_waterfall_is_complete_and_cited(self, stress):
        waterfall = stress["margin_call"]["waterfall"]
        assert len(waterfall) >= 8
        assert all(step["clause"] for step in waterfall)
        assert waterfall[-1]["label"] == "Transfer required"

    def test_allocation_reports_a_measured_saving(self, stress):
        allocation = stress["allocation"]
        assert allocation["status"] == "OPTIMAL"
        assert Decimal(allocation["total_cost"]["amount"]) < Decimal(
            allocation["baseline_cost"]["amount"]
        )
        assert Decimal(allocation["saving_percentage"]) > 0

    def test_wrong_way_asset_is_excluded_with_a_reason(self, stress):
        excluded = {e["asset_id"]: e["reason"] for e in stress["allocation"]["excluded"]}
        assert "US0000C2Y09" in excluded
        assert "11(g)(iv)" in excluded["US0000C2Y09"]

    def test_audit_chain_verifies(self, stress):
        assert stress["audit"]["verified"] is True
        assert stress["audit"]["break_at"] is None
        assert len(stress["audit"]["events"]) == 15

    def test_decision_requires_human_approval(self, stress):
        assert stress["decision"]["requires_human_approval"] is True
        assert "No financial transaction is executed" in stress["decision"]["disclaimer"]

    def test_base_scenario_generates_no_call(self, client):
        body = client.post("/api/v1/scenarios/base/run").json()
        assert body["margin_call"]["has_call"] is False
        assert body["decision"]["action"] == "NO_ACTION"
        assert body["allocation"] is None

    def test_unknown_scenario_is_a_404(self, client):
        response = client.post("/api/v1/scenarios/nonsense/run")
        assert response.status_code == 404
        assert "Available" in response.json()["detail"]


class TestExtractionAndReviewGate:
    """The API-level expression of the product's central rule."""

    def test_extraction_returns_cited_fields(self, client):
        body = client.post(f"/api/v1/documents/{DOCUMENT_ID}/extract").json()
        assert len(body["fields"]) == 21
        assert all(field["citation"] for field in body["fields"])
        assert body["mode"] in {"replay", "live"}

    def test_the_conditional_threshold_is_pending(self, client):
        body = client.get(f"/api/v1/documents/{DOCUMENT_ID}/terms").json()
        pending = body["pending_review"]
        assert len(pending) == 1
        assert pending[0]["path"] == "threshold.party_b"
        assert pending[0]["alternative"] == "USD 0.00"

    def test_freeze_is_refused_while_review_is_pending(self, client):
        client.post(f"/api/v1/documents/{DOCUMENT_ID}/extract")
        response = client.post(f"/api/v1/documents/{DOCUMENT_ID}/freeze")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["error"] == "REVIEW_REQUIRED"
        assert "threshold.party_b" in detail["pending"]

    def test_confirm_then_freeze_succeeds(self, client):
        client.post(f"/api/v1/documents/{DOCUMENT_ID}/extract")

        confirmed = client.post(
            f"/api/v1/documents/{DOCUMENT_ID}/confirm",
            json={
                "path": "threshold.party_b",
                "reviewer": "collateral.ops@aether.example",
                "rationale": "Party B rated AA-, above the A- trigger.",
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["is_ready_to_freeze"] is True

        frozen = client.post(f"/api/v1/documents/{DOCUMENT_ID}/freeze")
        assert frozen.status_code == 200
        assert frozen.json()["status"] == "FROZEN"

    def test_confirmation_without_rationale_is_refused(self, client):
        client.post(f"/api/v1/documents/{DOCUMENT_ID}/extract")
        response = client.post(
            f"/api/v1/documents/{DOCUMENT_ID}/confirm",
            json={"path": "threshold.party_b", "reviewer": "ops", "rationale": "  "},
        )
        assert response.status_code == 422

    def test_unknown_document_is_a_404(self, client):
        assert client.post("/api/v1/documents/NOPE/extract").status_code == 404


class TestEvaluationEndpoint:
    def test_reports_measured_accuracy(self, client):
        body = client.get(f"/api/v1/documents/{DOCUMENT_ID}/evaluation").json()
        assert body["scored_fields"] == 21
        assert Decimal(body["review_flag_recall"]) == Decimal("1.000")
        assert body["passes"] is True


class TestReferenceData:
    def test_inventory_is_labelled_simulated(self, client):
        body = client.get("/api/v1/collateral/inventory").json()
        assert body["simulated"] is True
        assert len(body["assets"]) == 12

    def test_snapshots_carry_a_simulated_warning(self, client):
        body = client.get("/api/v1/market/snapshots").json()
        assert body["simulated"] is True
        assert "Simulated" in body["warning"]

    def test_agreement_round_trips(self, client):
        body = client.get(f"/api/v1/agreements/{DOCUMENT_ID}").json()
        assert body["base_currency"] == "USD"
        assert len(body["eligible_collateral"]) == 10
        assert body["excluded_issuers"] == ["MERIDIAN_GLOBAL"]
