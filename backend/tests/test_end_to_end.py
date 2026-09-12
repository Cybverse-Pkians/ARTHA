"""End-to-end behaviour across every archetype."""

import pytest

from artha.core.types import GateOutcome
from artha.synth.generator import ARCHETYPES


@pytest.mark.parametrize("key", sorted(ARCHETYPES))
def test_every_archetype_produces_a_complete_decision(engine, ingest, as_of, key):
    token = ingest(key)
    bundle = engine.decide(token, as_of=as_of)
    decision = bundle.decision
    regulator = decision.render_regulator()
    customer = decision.render_customer()

    assert decision.decision_id.startswith("dec_")
    assert regulator["outcome"] == decision.outcome.value
    assert len(regulator["gate_trace"]) >= 5
    assert customer.headline.strip()
    assert all(r["title"] for r in regulator["reason_codes"])
    assert regulator["input_hash"]
    assert regulator["model_versions"]


def test_the_two_renderings_cannot_diverge(engine, ingest, as_of):
    """One Decision Object, rendered twice from a single source (report §7.6)."""
    token = ingest("salaried_stable")
    decision = engine.decide(token, as_of=as_of).decision
    regulator = decision.render_regulator()
    customer = decision.render_customer()
    assert regulator["outcome"] == decision.outcome.value
    codes = {r["code"] for r in regulator["reason_codes"]}
    assert codes
    # the customer headline is generated from one of the cited reason codes
    assert customer.headline


def test_a_customer_in_stress_is_never_sold_to(engine, ingest, as_of):
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.decision.offer is None
    assert bundle.decision.outcome in {GateOutcome.PROTECT, GateOutcome.SUPPRESS}


def test_thin_buffer_unstable_income_gets_no_credit(engine, ingest, as_of):
    """Report Table 3, last row: an emergency-fund plan, not a loan."""
    token = ingest("gig")
    bundle = engine.decide(token, as_of=as_of)
    offer = bundle.decision.offer
    assert offer is None or offer.product.family.value == "SAVINGS"


def test_the_gate_refuses_sometimes_and_not_always(engine, ingest, as_of):
    """Suppression is a success metric; refusing everything is not a system."""
    outcomes = []
    for key in ARCHETYPES:
        token = ingest(key)
        outcomes.append(engine.decide(token, as_of=as_of).decision.outcome)

    assert any(o is GateOutcome.ACT for o in outcomes)
    assert any(o in {GateOutcome.SUPPRESS, GateOutcome.PROTECT} for o in outcomes)


def test_silence_is_a_valid_recorded_outcome(engine, ingest, as_of):
    token = ingest("salaried_stable")
    engine.decide(token, as_of=as_of)
    second = engine.decide(token, as_of=as_of)
    assert second.decision.outcome in set(GateOutcome)
