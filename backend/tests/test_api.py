"""API smoke tests.

These exercise the FastAPI layer through its own TestClient. They are skipped
where fastapi is unavailable — notably under the Pyodide harness in `tools/`,
which is how the engine suite was executed on a machine without a Python
toolchain. **They have therefore not been run yet.** Run them first on any
machine that can install `requirements-dev.txt`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="API layer requires fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from artha.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_reference_endpoints(client):
    assert client.get("/catalogue").json()["products"]
    assert client.get("/reason-codes").json()["codes"]
    assert client.get("/archetypes").json()["archetypes"]
    assert client.get("/policy").json()["excluded_data_sources"]


def test_seed_then_decide(client):
    seeded = client.post("/seed", json={"archetype": "salaried_stable"})
    assert seeded.status_code == 200
    token = seeded.json()["customer_token"]
    assert "SYNTHETIC" in seeded.json()["data_provenance"]

    decided = client.post("/decide", json={"customer_token": token})
    assert decided.status_code == 200
    body = decided.json()

    assert body["outcome"] in {"ACT", "SUPPRESS", "PROTECT", "VERIFY"}
    assert body["customer"]["headline"]
    assert len(body["regulator"]["gate_trace"]) >= 5
    assert body["regulator"]["input_hash"]
    assert "data_provenance" in body


def test_decide_on_an_unknown_customer_is_404(client):
    assert client.post("/decide", json={"customer_token": "tok_nobody"}).status_code == 404


def test_render_validates_against_the_stored_decision(client):
    """The firewall must check numerals against the decision being phrased."""
    token = client.post("/seed", json={"archetype": "salaried_stable"}).json()["customer_token"]
    decided = client.post("/decide", json={"customer_token": token}).json()
    decision_id = decided["decision_id"]

    honest = client.post("/render", json={
        "decision_id": decision_id, "customer_token": token,
        "model_text": decided["customer"]["spoken"],
    }).json()
    assert honest["allowed"] is True

    hallucinated = client.post("/render", json={
        "decision_id": decision_id, "customer_token": token,
        "model_text": "You are approved for ₹7,43,219 at 8.25%.",
    }).json()
    assert hallucinated["allowed"] is False
    assert hallucinated["outcome"] == "BLOCKED_UNGROUNDED_NUMBER"
    assert hallucinated["used_fallback"] is True


def test_render_with_an_unknown_decision_is_404(client):
    token = client.post("/seed", json={"archetype": "gig"}).json()["customer_token"]
    response = client.post("/render", json={
        "decision_id": "dec_doesnotexist", "customer_token": token,
        "model_text": "hello",
    })
    assert response.status_code == 404


def test_render_does_not_mutate_state(client):
    """A validation call must not record a decision or spend a nudge budget."""
    token = client.post("/seed", json={"archetype": "salaried_stable"}).json()["customer_token"]
    decision_id = client.post("/decide", json={"customer_token": token}).json()["decision_id"]

    before = client.get("/audit/records?limit=500&record_type=DECISION").json()["count"]
    client.post("/render", json={
        "decision_id": decision_id, "customer_token": token, "model_text": "ok",
    })
    after = client.get("/audit/records?limit=500&record_type=DECISION").json()["count"]
    assert after == before


def test_banker_surfaces(client):
    client.post("/seed", json={"archetype": "stressed"})
    assert "queue" in client.get("/banker/queue").json()
    assert "slices" in client.get("/banker/fairness").json()
    assert client.get("/banker/suppression").json()["trend_indicator"] == "positive"
    assert "customer" in client.get("/banker/dual-ledger").json()


def test_audit_chain_verifies_over_the_api(client):
    assert client.get("/audit/verify").json()["verified"] is True


def test_journey_slot_gating(client):
    body = client.post("/journey/slot", json={
        "text": "mujhe ek lakh chahiye", "asr_confidence": 0.93, "language": "hi",
    }).json()
    assert body["value"] == 100_000 * 100
    assert body["needs_reask"] is True          # large amount, always read back


def test_consent_revocation_is_enforced(client):
    token = client.post("/seed", json={"archetype": "salaried_stable"}).json()["customer_token"]
    revoked = client.post("/journey/consent", json={
        "customer_token": token, "purpose": "PRODUCT_RECOMMENDATION", "grant": False,
    })
    assert revoked.status_code == 200

    body = client.post("/decide", json={"customer_token": token}).json()
    assert body["outcome"] != "ACT"


def test_non_withdrawable_consent_is_refused(client):
    token = client.post("/seed", json={"archetype": "gig"}).json()["customer_token"]
    response = client.post("/journey/consent", json={
        "customer_token": token, "purpose": "FRAUD_MONITORING", "grant": False,
    })
    assert response.status_code == 400
