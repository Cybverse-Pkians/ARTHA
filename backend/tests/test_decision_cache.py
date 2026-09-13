"""Asking twice is not deciding twice.

Deciding has side effects: it consumes the customer's nudge budget, records a
fairness observation and writes to the audit log. The surfaces re-request
decisions constantly — every console page load, every scenario switch — so
without a cache the second request was a second contact, the product cooldown
suppressed the offer, and the customer's answer changed because somebody had
refreshed a browser.

The cache therefore has to satisfy two opposing promises at once, and both are
asserted here:

* a repeated request is a **read** — same answer, no new contact, no new audit
  record;
* anything that could change the answer **invalidates it**, however it was done
  — through the API, or by reaching into the components directly.
"""

from __future__ import annotations

import pytest

from artha.audit.log import RecordType
from artha.core.types import RecoveryState
from artha.engines.twin import path_day_offsets


def _decisions_logged(engine, token) -> int:
    return sum(
        1 for r in engine.audit.for_customer(token)
        if r.record_type is RecordType.DECISION
    )


def test_deciding_twice_returns_the_same_decision(engine, ingest, as_of):
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    second = engine.decide(token, as_of=as_of)
    assert first is second
    assert first.decision.decision_id == second.decision.decision_id


def test_a_repeated_request_does_not_consume_the_nudge_budget(engine, ingest, as_of):
    """The bug this cache exists for.

    With a four-contact monthly budget and a 45-day product cooldown, a handful
    of page loads used to exhaust the customer's budget and flip their answer
    from an offer to a suppression.
    """
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    if first.decision.offer is None:
        pytest.skip("this archetype was not offered anything to begin with")

    remaining = engine.budget.remaining(token, as_of)
    for _ in range(6):
        again = engine.decide(token, as_of=as_of)
        assert again.decision.outcome is first.decision.outcome
        assert again.decision.offer is not None

    assert engine.budget.remaining(token, as_of) == remaining


def test_a_repeated_request_does_not_grow_the_audit_log(engine, ingest, as_of):
    token = ingest("salaried_stable")
    engine.decide(token, as_of=as_of)
    logged = _decisions_logged(engine, token)
    for _ in range(4):
        engine.decide(token, as_of=as_of)
    assert _decisions_logged(engine, token) == logged


def test_a_different_request_is_a_different_question(engine, ingest, as_of):
    """Asking about a specific amount is not the same question as asking in general.

    The general answer is *not* asserted to survive afterwards, and that is
    deliberate: reaching a second decision can record a contact, which is a real
    change to the customer's conduct state and must invalidate what came before
    it. The cache exists to stop a repeated question being re-answered, not to
    freeze an answer across genuine state changes.
    """
    token = ingest("salaried_stable")
    plain = engine.decide(token, as_of=as_of)
    asked = engine.decide(token, as_of=as_of, requested_amount_paise=50_000_00)
    assert plain is not asked

    # Each question, asked twice in a row, is answered once.
    assert engine.decide(token, as_of=as_of, requested_amount_paise=50_000_00) is asked


def test_re_ingesting_invalidates_the_cache(engine, ingest, as_of):
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    state = engine.state(token)
    engine.ingest(
        token, state.transactions, balance_paise=state.profile.balance_paise, as_of=as_of
    )
    assert engine.decide(token, as_of=as_of) is not first


def test_a_recovery_transition_invalidates_the_cache(engine, ingest, as_of):
    """Reaching past the API must not leave a stale answer behind.

    Recovery Mode is the one thing that overrides every other outcome, so a
    cached decision that outlived a transition into it would be a customer in
    distress still being shown an offer.
    """
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    engine.recovery.transition(
        token, RecoveryState.AT_RISK, reason="test", evidence=("test",), at=as_of
    )
    second = engine.decide(token, as_of=as_of)
    assert second is not first
    assert second.decision.offer is None


def test_a_consent_change_invalidates_the_cache(engine, ingest, as_of):
    from artha.consent.purposes import Purpose

    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    assert engine.consent.revoke(token, Purpose.PRODUCT_RECOMMENDATION)
    assert engine.decide(token, as_of=as_of) is not first


def test_recording_a_decline_invalidates_the_cache(engine, ingest, as_of):
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of)
    if first.decision.offer is None:
        pytest.skip("nothing was offered, so nothing can be declined")
    engine.recovery.record_decline(
        token, family=first.decision.offer.product.family.value, do_not_ask_again=True
    )
    assert engine.decide(token, as_of=as_of) is not first


def test_reading_the_decision_in_another_language_is_not_a_second_contact(
    engine, ingest, as_of
):
    """Switching language is a rendering choice, not a new decision.

    Keying the cache on language meant a customer flipping through the five
    languages the app offers spent their entire monthly nudge budget doing it,
    and was then met with silence — the conduct control firing on the act of
    reading rather than on anything the bank did.
    """
    token = ingest("salaried_stable")
    first = engine.decide(token, as_of=as_of, language="hi")
    remaining = engine.budget.remaining(token, as_of)

    for lang in ("en", "mr", "ta", "bn", "hi"):
        assert engine.decide(token, as_of=as_of, language=lang) is first

    assert engine.budget.remaining(token, as_of) == remaining


def test_the_same_decision_renders_in_every_language(engine, ingest, as_of):
    """One decision, five renderings — and none of them falls back to English."""
    token = ingest("salaried_stable")
    bundle = engine.decide(token, as_of=as_of)
    renderings = {
        lang: bundle.decision.render_customer(lang)
        for lang in ("en", "hi", "mr", "ta", "bn")
    }
    for lang, rendering in renderings.items():
        assert rendering.headline, f"no headline rendered for {lang}"
        assert rendering.language == lang
    # The four vernacular renderings are each distinct from the English one,
    # which is what distinguishes a translation from a silent fallback.
    english = renderings["en"].headline
    for lang in ("hi", "mr", "ta", "bn"):
        assert renderings[lang].headline != english, f"{lang} fell back to English"


def test_one_customer_does_not_invalidate_another(engine, ingest, as_of):
    """The console decides every customer in a row; that must not thrash."""
    a = ingest("salaried_stable")
    b = ingest("business")
    first_a = engine.decide(a, as_of=as_of)
    engine.decide(b, as_of=as_of)
    assert engine.decide(a, as_of=as_of) is first_a


# --- a customer who asks -----------------------------------------------------


def test_asking_for_an_amount_is_itself_a_moment(engine, ingest, as_of):
    """Silence is for when the bank has nothing to say, not when the customer speaks."""
    token = ingest("salaried_stable")
    asked = engine.decide(token, as_of=as_of, requested_amount_paise=60_000_00)
    triggers = {m.trigger for m in asked.moments}
    # Either a real moment fired anyway, or the request supplied one; what must
    # not happen is the request being ignored and the customer told nothing.
    assert triggers, "a customer who asked for an amount must not be met with silence"


# --- chart sampling ---------------------------------------------------------


def test_path_day_offsets_cover_the_whole_horizon():
    """The last sample is the last day, not several days short of it.

    The chart used to spread evenly-indexed samples across the horizon, so with a
    180-day horizon the final point was day 174 and the axis labelled it 180 —
    every reading the customer took off the chart was wrong by up to a week, on
    the screen the report calls the consent screen.
    """
    days = path_day_offsets(180)
    assert days[0] == 0
    assert days[-1] == 179
    assert list(days) == sorted(days)
    assert len(set(days)) == len(days)


@pytest.mark.parametrize("horizon", [7, 30, 90, 180, 365])
def test_sampling_stays_well_formed_at_any_horizon(horizon):
    days = path_day_offsets(horizon)
    assert days[0] == 0
    assert days[-1] == horizon - 1
    assert all(0 <= d < horizon for d in days)


def test_the_paths_and_their_day_offsets_are_the_same_length(engine, ingest, as_of):
    token = ingest("salaried_stable")
    twin = engine.decide(token, as_of=as_of).decision.twin
    assert twin is not None
    assert len(twin.path_days) == len(twin.path_with) == len(twin.path_without)
    assert len(twin.path_p05) == len(twin.path_with)
    assert twin.horizon_days > 0
    assert twin.path_days[-1] == twin.horizon_days - 1


def test_a_loan_request_is_never_answered_with_another_product(engine, ingest, as_of):
    """Asking for a loan must not be answered with a savings product.

    The conduct controls can legitimately block every loan the customer asked
    about — a cooldown, an exhausted nudge budget. What the pipeline must not do
    then is walk on to whatever the Moment Engine happened to detect and present
    that as the answer: someone asking for ₹1,50,000 was offered a ₹208-a-month
    recurring deposit, which is a cross-sell wearing the clothes of a reply.
    """
    from artha.core.types import ProductFamily

    token = ingest("salaried_stable")
    # Use up the loan family's cooldown with an ordinary decision first.
    engine.decide(token, as_of=as_of)

    asked = engine.decide(token, as_of=as_of, requested_amount_paise=150_000_00)
    offer = asked.decision.offer
    if offer is not None:
        assert offer.product.family is ProductFamily.LOAN, (
            f"a loan request was answered with {offer.product.product_id}"
        )


def test_a_blocked_request_still_gets_a_counterfactual(engine, ingest, as_of):
    """A refusal without a structure that would work is a pipeline failure."""
    token = ingest("salaried_stable")
    asked = engine.decide(token, as_of=as_of, requested_amount_paise=150_000_00)
    d = asked.decision
    if d.offer is None:
        assert d.counterfactual is not None, "a refused request carried no counterfactual"
