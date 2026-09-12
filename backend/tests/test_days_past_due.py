"""Deriving days past due, and carrying both ladders on the Decision Object.

``days_past_due`` is the producer that stops ``core/asset_class`` being an
orphan module. Its failure modes matter more than its happy path: a wrongly
classified account changes how a real person is contacted, so every ambiguity
resolves towards Standard.
"""

from __future__ import annotations

from datetime import date

import pytest

from artha.core.asset_class import SmaState
from artha.features.builder import days_past_due, last_due_date

AS_OF = date(2026, 9, 12)


# --- due-date arithmetic ----------------------------------------------------

def test_the_most_recent_due_date_is_this_month_once_it_has_passed():
    assert last_due_date(5, date(2026, 9, 12)) == date(2026, 9, 5)


def test_before_this_months_due_date_the_last_one_was_last_month():
    assert last_due_date(20, date(2026, 9, 12)) == date(2026, 8, 20)


def test_a_due_date_past_the_end_of_the_month_is_clamped():
    """A 31st due date must not vanish in February."""
    assert last_due_date(31, date(2026, 3, 15)) == date(2026, 2, 28)
    assert last_due_date(31, date(2026, 5, 15)) == date(2026, 4, 30)


def test_january_rolls_back_to_december():
    assert last_due_date(25, date(2026, 1, 10)) == date(2025, 12, 25)


# --- fails towards Standard -------------------------------------------------

def test_a_customer_with_no_emi_series_is_not_past_due(engine, ingest, as_of):
    """Not past due on a loan they may not have."""
    token = ingest("thin_file_woman")
    st = engine.state(token)
    assert days_past_due(st.profile, st.enriched, as_of=as_of) == 0


def test_an_empty_history_is_not_past_due(engine, ingest, as_of):
    token = ingest("salaried_stable")
    st = engine.state(token)
    assert days_past_due(st.profile, [], as_of=as_of) == 0


def test_a_healthy_salaried_customer_is_standard(engine, ingest, as_of):
    """Regression: a feed ending a few days early is missing data, not arrears.

    Before the observation-window guard this archetype reported SMA-0 purely
    because the generated history stopped before the next due date.
    """
    token = ingest("salaried_stable")
    st = engine.state(token)
    assert days_past_due(st.profile, st.enriched, as_of=as_of) == 0


def test_a_stale_feed_does_not_manufacture_delinquency(engine, ingest, as_of):
    """Asserting non-payment requires having been able to observe payment."""
    token = ingest("salaried_stable")
    st = engine.state(token)
    far_future = date(as_of.year + 1, as_of.month, as_of.day)
    assert days_past_due(st.profile, st.enriched, as_of=far_future) == 0


# --- both ladders on the decision -------------------------------------------

def test_the_decision_carries_the_supervisory_position(engine, ingest, as_of):
    token = ingest("stressed")
    d = engine.decide(token, as_of=as_of).decision
    assert isinstance(d.sma_state, SmaState)
    assert d.days_past_due >= 0
    assert d.asset.state is d.sma_state


def test_the_regulator_rendering_shows_both_ladders(engine, ingest, as_of):
    """A claim about the distance between them cannot be audited from one end."""
    token = ingest("stressed")
    d = engine.decide(token, as_of=as_of).decision
    rendered = d.render_regulator()
    assert "recovery_state" in rendered
    assert "sma_state" in rendered
    assert "days_past_due" in rendered
    assert rendered["supervisory_gap"]["asset_classification"]["state"] == d.sma_state.value


def test_a_decision_survives_reconstruction_from_its_audit_record(engine, ingest, as_of):
    """The new fields must round-trip, or the audit trail loses them."""
    from artha.core.decision import DecisionObject

    token = ingest("stressed")
    original = engine.decide(token, as_of=as_of).decision
    restored = DecisionObject.from_regulator_rendering(original.render_regulator())
    assert restored.days_past_due == original.days_past_due
    assert restored.sma_state is original.sma_state


@pytest.mark.parametrize(
    "archetype", ["gig", "high_cost_borrower"]
)
def test_the_system_acts_while_the_account_is_still_standard(engine, ingest, as_of, archetype):
    """The central claim, now measurable rather than asserted."""
    token = ingest(archetype)
    d = engine.decide(token, as_of=as_of).decision
    gap = d.supervisory_gap
    assert d.sma_state is SmaState.STANDARD
    assert gap.acting_early is True
    assert gap.lead > 0
