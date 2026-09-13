"""The Suitability Gate — six checks, four outcomes (report §5.2)."""

from datetime import timedelta

from artha.consent.purposes import Purpose
from artha.core.types import GateOutcome, RecoveryState
from artha.gate.conduct import LifeEvent


def test_gate_trace_records_every_check_not_only_the_failure(engine, ingest, as_of):
    """A trace that stops at the first failure cannot show the others ran."""
    token = ingest("salaried_stable")
    bundle = engine.decide(token, as_of=as_of)
    names = [c.name for c in bundle.gate.trace]
    for expected in (
        "consent_purpose", "eligibility", "affordability",
        "recovery_mode", "nudge_budget", "empathy_calendar", "fairness",
    ):
        assert expected in names


def test_recovery_mode_suppresses_selling_in_every_family(engine, ingest, as_of):
    """The defining safeguard of the system (report §9.3)."""
    token = ingest("salaried_stable")
    engine.recovery.transition(
        token, RecoveryState.RECOVERY, reason="test", at=as_of
    )
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.decision.offer is None
    assert bundle.decision.outcome is not GateOutcome.ACT


def test_exhausted_nudge_budget_suppresses(engine, ingest, as_of):
    token = ingest("salaried_stable")
    for i in range(engine.budget.per_month):
        engine.budget.record_contact(token, f"FILLER_{i}", as_of)
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.decision.outcome is not GateOutcome.ACT
    assert bundle.gate.blocking_check == "nudge_budget"


def test_empathy_calendar_suppresses_during_bereavement(engine, ingest, as_of):
    token = ingest("salaried_stable")
    engine.calendar.add(
        token, LifeEvent.BEREAVEMENT, start=as_of - timedelta(days=5), evidence="test"
    )
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.decision.outcome is not GateOutcome.ACT
    assert bundle.gate.blocking_check == "empathy_calendar"


def test_revoking_a_purpose_stops_the_recommendation_at_inference_time(engine, ingest, as_of):
    """Privacy is enforced in the data layer, not asserted in a policy (§9.1)."""
    token = ingest("salaried_stable")
    engine.consent.revoke(token, Purpose.PRODUCT_RECOMMENDATION)
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.decision.outcome is not GateOutcome.ACT
    assert bundle.gate.blocking_check == "consent_purpose"


def test_do_not_ask_again_is_honoured(engine, ingest, as_of):
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    if first.decision.offer is None:
        return
    family = first.decision.offer.product.family.value
    engine.recovery.record_decline(token, family=family, do_not_ask_again=True)
    second = engine.decide(token, as_of=as_of)
    if second.decision.offer is not None:
        assert second.decision.offer.product.family.value != family


def test_declining_is_not_treated_as_a_risk_signal(engine, ingest, as_of):
    """Report §6.5: the customer may have income the bank cannot see."""
    token = ingest("salaried_stable")
    before = engine.recovery.get(token).state
    engine.recovery.record_decline(token, family="LOAN")
    assert engine.recovery.get(token).state is before


def test_offers_are_sized_at_or_below_eligibility(engine, ingest, as_of):
    from artha.core.money import rupees

    token = ingest("salaried_stable")
    bundle = engine.decide(
        token, as_of=as_of,
        requested_product_id="pl_standard",
        requested_amount_paise=rupees(500_000),
    )
    offer = bundle.decision.offer
    if offer is not None:
        assert offer.amount_paise <= offer.eligible_amount_paise
        assert offer.amount_paise <= rupees(500_000)


# --- inbound requests versus unsolicited contact -----------------------------


def test_the_contact_cap_does_not_silence_a_reply(engine, ingest, as_of):
    """Frequency caps govern unprompted contact, not answers.

    The nudge budget and the per-product cooldown exist so the bank cannot
    pester. Applying them to a question the customer asked means answering
    "we showed you this recently" to someone who has just asked — a refusal to
    answer dressed as restraint.
    """
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    if first.decision.offer is None:
        pytest.skip("nothing was offered unprompted, so no cooldown was set")

    asked = engine.decide(token, as_of=as_of, requested_amount_paise=100_000_00)
    blocking = asked.gate.blocking_check
    assert blocking not in {"nudge_budget", "product_cooldown"}, (
        f"an inbound request was blocked by {blocking}"
    )


def test_answering_does_not_spend_the_customers_contact_budget(engine, ingest, as_of):
    """A reply is not a nudge, so it must not consume the customer's allowance."""
    token = ingest("salaried_stable")
    before = engine.budget.remaining(token, as_of)
    engine.decide(token, as_of=as_of, requested_amount_paise=100_000_00)
    assert engine.budget.remaining(token, as_of) == before


def test_an_inbound_request_still_respects_do_not_ask_again(engine, ingest, as_of):
    """The one conduct control that is the customer's own instruction."""
    from artha.core.types import ProductFamily

    token = ingest("salaried_stable")
    engine.recovery.record_decline(
        token, family=ProductFamily.LOAN.value, do_not_ask_again=True
    )
    asked = engine.decide(token, as_of=as_of, requested_amount_paise=100_000_00)
    offer = asked.decision.offer
    assert offer is None or offer.product.family is not ProductFamily.LOAN


def test_an_inbound_request_is_still_suppressed_in_recovery(engine, ingest, as_of):
    """Asking does not unlock selling to a customer the system is protecting."""
    token = ingest("sma2_missed_thrice")
    asked = engine.decide(token, as_of=as_of, requested_amount_paise=100_000_00)
    assert asked.decision.offer is None
