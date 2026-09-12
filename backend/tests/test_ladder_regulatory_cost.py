"""Typed regulatory cost, and lead time actually constraining the ladder.

Both were claims the code did not make good on. ``regulatory_cost`` was English
prose that every caller rendered and none branched on, and ``lead_time_to_rung``
— described in the module as "the function that converts model quality into
money" — had no caller outside the test suite because ``build()`` took no lead
time at all.
"""

from __future__ import annotations

import pytest

from artha.core.types import PayIntent
from artha.intervention.ladder import (
    InterventionLadder,
    RegCost,
    Rung,
    lead_time_to_rung,
)


def _build(profile, *, lead_time_days=None, emi=100_000, day=8, as_of=None):
    return InterventionLadder().build(
        profile,
        current_emi_paise=emi,
        current_day_of_month=day,
        remaining_tenure_months=24,
        annual_rate=0.145,
        outstanding_paise=emi * 24,
        pay_intent=PayIntent.UNABLE,
        lead_time_days=lead_time_days,
        as_of=as_of,
    )


# --- typed regulatory cost --------------------------------------------------

def test_the_cheapest_rung_is_the_one_artha_may_propose_on_its_own(engine, ingest, as_of):
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    recommended = bundle.ladder.recommended
    assert recommended.reg_cost is RegCost.NONE
    assert recommended.reg_cost.auto_proposable is True
    assert recommended.reg_cost.requires_human_credit_officer is False


def test_restructuring_rungs_are_never_auto_proposable(engine, ingest, as_of):
    """The rungs that cost the bank an asset downgrade need a human."""
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    rungs = [bundle.ladder.recommended, *bundle.ladder.alternatives]
    costly = [
        i for i in rungs
        if i.rung in {Rung.TENURE_EXTENSION, Rung.FORMAL_RESTRUCTURE}
    ]
    assert costly, "expected the expensive rungs to be offered as alternatives"
    for i in costly:
        assert i.reg_cost is RegCost.DOWNGRADE_EXPECTED
        assert i.reg_cost.requires_human_credit_officer is True
        assert i.reg_cost.auto_proposable is False


def test_regulatory_cost_rises_monotonically_with_the_rung(engine, ingest, as_of):
    """A more expensive rung must never carry a cheaper supervisory cost."""
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    rungs = sorted(
        [bundle.ladder.recommended, *bundle.ladder.alternatives],
        key=lambda i: i.rung,
    )
    costs = [int(i.reg_cost) for i in rungs]
    assert costs == sorted(costs)


def test_the_prose_is_retained_alongside_the_typed_value(engine, ingest, as_of):
    """The type says what to do; the prose still says why."""
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    for i in [bundle.ladder.recommended, *bundle.ladder.alternatives]:
        assert i.regulatory_cost.strip()
        assert isinstance(i.reg_cost, RegCost)


# --- lead time now constrains -----------------------------------------------

def test_ample_lead_time_leaves_the_cheapest_rung_available(engine, ingest, as_of):
    token = ingest("stressed")
    profile = engine.state(token).profile
    result = _build(profile, lead_time_days=30, as_of=as_of)
    assert result.recommended.rung is Rung.EMI_DATE_SHIFT


def test_short_lead_time_withdraws_rungs_there_is_no_time_to_execute(engine, ingest, as_of):
    """Three days before a due date, moving that date is not a remedy."""
    token = ingest("stressed")
    profile = engine.state(token).profile
    result = _build(profile, lead_time_days=4, as_of=as_of)
    assert result.recommended.rung >= lead_time_to_rung(4)
    assert result.recommended.rung is not Rung.EMI_DATE_SHIFT


def test_no_lead_time_at_all_escalates_to_the_most_expensive_rung(engine, ingest, as_of):
    token = ingest("stressed")
    profile = engine.state(token).profile
    result = _build(profile, lead_time_days=-5, as_of=as_of)
    assert result.recommended.rung is Rung.FORMAL_RESTRUCTURE


def test_unknown_lead_time_does_not_constrain_the_ladder(engine, ingest, as_of):
    """Unknown is not the same as "no time left".

    Treating a missing lead time as zero would silently escalate every customer
    whose due date could not be located to a formal restructure.
    """
    token = ingest("stressed")
    profile = engine.state(token).profile
    unconstrained = _build(profile, lead_time_days=None, as_of=as_of)
    assert unconstrained.recommended.rung is Rung.EMI_DATE_SHIFT


def test_the_ladder_is_never_left_empty_by_the_floor(engine, ingest, as_of):
    """An empty ladder would silently become a refusal."""
    token = ingest("stressed")
    profile = engine.state(token).profile
    for lead in (-30, -1, 0, 3, 10, 21, 90):
        result = _build(profile, lead_time_days=lead, as_of=as_of)
        assert result.has_recommendation, f"empty ladder at lead_time={lead}"


@pytest.mark.parametrize("lead", [90, 21, 12, 5, 1, -5])
def test_less_lead_time_never_yields_a_cheaper_rung(engine, ingest, as_of, lead):
    """Monotonicity: buying time can only ever help."""
    token = ingest("stressed")
    profile = engine.state(token).profile
    ample = _build(profile, lead_time_days=90, as_of=as_of).recommended.rung
    actual = _build(profile, lead_time_days=lead, as_of=as_of).recommended.rung
    assert actual >= ample


# --- rung 2 now exists ------------------------------------------------------

def test_the_split_instalment_rung_can_actually_be_constructed(engine, ingest, as_of):
    """Declared in the enum and selectable by lead time, but never built."""
    token = ingest("gig")
    profile = engine.state(token).profile
    result = _build(profile, as_of=as_of)
    all_rungs = [result.recommended, *result.alternatives]
    split = next((i for i in all_rungs if i.rung is Rung.PARTIAL_PREPAYMENT_PLAN), None)
    assert split is not None, "rung 2 is still unreachable"
    assert split.reg_cost is RegCost.NONE
    assert split.economic_cost_paise == 0


def test_a_split_is_not_offered_to_single_credit_salaried_income(engine, ingest, as_of):
    """It would add a debit without adding relief."""
    token = ingest("salaried_stable")
    profile = engine.state(token).profile
    result = _build(profile, as_of=as_of)
    all_rungs = [result.recommended, *result.alternatives]
    assert not any(i.rung is Rung.PARTIAL_PREPAYMENT_PLAN for i in all_rungs)


def test_collections_is_not_an_intervention_the_ladder_can_recommend(engine, ingest, as_of):
    """Rung 6 is the absence of an intervention, not one of them."""
    token = ingest("stressed")
    profile = engine.state(token).profile
    result = _build(profile, as_of=as_of)
    all_rungs = [result.recommended, *result.alternatives]
    assert not any(i.rung is Rung.COLLECTIONS for i in all_rungs)
