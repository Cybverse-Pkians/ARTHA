"""The AI Firewall — the language model is the mouth, not the brain (§7.7)."""

import pytest

from artha.llm.capability import Capability, CapabilityBroker, TokenRejected
from artha.llm.firewall import AIFirewall, FirewallOutcome, build_model_context


@pytest.fixture
def decision(engine, ingest, as_of):
    token = ingest("salaried_stable")
    return engine.decide(token, as_of=as_of).decision


def test_the_systems_own_rendering_passes(decision):
    fw = AIFirewall()
    verdict = fw.validate(decision.render_customer().spoken, decision)
    assert verdict.outcome is FirewallOutcome.ALLOWED


def test_hallucinated_numbers_are_blocked(decision):
    """The most dangerous failure mode in regulated lending."""
    fw = AIFirewall()
    verdict = fw.validate("You are approved for ₹7,43,219 at 8.25%.", decision)
    assert verdict.outcome is FirewallOutcome.BLOCKED_UNGROUNDED_NUMBER
    assert verdict.used_fallback
    assert verdict.text == decision.render_customer().spoken


def test_devanagari_numerals_are_checked_too(decision):
    fw = AIFirewall()
    assert not fw.validate("आपको ९९९९९९ रुपये मिलेंगे।", decision).allowed


@pytest.mark.parametrize(
    "text",
    [
        "Please share the OTP sent to your phone.",
        "Hurry — this offer expires in 2 hours!",
        "You are guaranteed approval for this loan.",
        "I have approved your loan.",
    ],
)
def test_forbidden_content_is_blocked(decision, text):
    assert not AIFirewall().validate(text, decision).allowed


def test_anti_phishing_assurance_is_allowed_in_any_language(decision):
    """ARTHA must be able to say it will never ask for an OTP — in Hindi too.

    An English-only exemption blocks the system's own vernacular safety message
    while passing an English phishing attempt containing the word "never".
    """
    fw = AIFirewall()
    assert fw.validate("We will never ask you for an OTP or PIN.", decision).allowed
    assert fw.validate("हम कभी OTP या PIN नहीं मांगेंगे।", decision).allowed


def test_model_context_carries_no_identifying_data(decision):
    """Full model compromise leaks nothing identifying (report §7.7)."""
    context = build_model_context(decision)
    blob = str(context)
    assert decision.customer_token not in blob
    assert context["allowed_numbers"]


def test_capability_tokens_require_confirmation_and_are_single_use(decision):
    broker = CapabilityBroker(secret="test", ttl_seconds=300)
    token = broker.mint(
        Capability.ACCEPT_OFFER,
        decision_id=decision.decision_id,
        customer_token=decision.customer_token,
    )

    with pytest.raises(TokenRejected):
        broker.redeem(token, customer_confirmed=False)

    broker.redeem(token, customer_confirmed=True, expected_capability=Capability.ACCEPT_OFFER)

    with pytest.raises(TokenRejected):
        broker.redeem(token, customer_confirmed=True)


def test_capability_scope_is_enforced(decision):
    broker = CapabilityBroker(secret="test")
    token = broker.mint(
        Capability.PRESENT_OFFER, decision_id="d", customer_token="tok"
    )
    with pytest.raises(TokenRejected):
        broker.redeem(
            token, customer_confirmed=True, expected_capability=Capability.ACCEPT_OFFER
        )


def test_a_forged_signature_is_rejected(decision):
    from dataclasses import replace

    broker = CapabilityBroker(secret="test")
    token = broker.mint(Capability.ACCEPT_OFFER, decision_id="d", customer_token="tok")
    forged = replace(token, signature="0" * 64)
    with pytest.raises(TokenRejected):
        broker.redeem(forged, customer_confirmed=True)
