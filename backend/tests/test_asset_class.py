"""The supervisory ladder, and its distance from the behavioural one."""

from __future__ import annotations

import pytest

from artha.core.asset_class import (
    NPA_THRESHOLD_DAYS,
    AssetClassification,
    SmaState,
    SupervisoryGap,
    classify,
    classify_revolving,
    days_until,
)


# --- band boundaries --------------------------------------------------------

@pytest.mark.parametrize(
    "dpd,expected",
    [
        (-5, SmaState.STANDARD),   # paid ahead of the due date
        (0, SmaState.STANDARD),    # due today, unpaid — still Standard
        (1, SmaState.SMA_0),
        (30, SmaState.SMA_0),
        (31, SmaState.SMA_1),
        (60, SmaState.SMA_1),
        (61, SmaState.SMA_2),
        (90, SmaState.SMA_2),
        (91, SmaState.NPA),
        (400, SmaState.NPA),
    ],
)
def test_every_band_boundary(dpd: int, expected: SmaState):
    assert classify(dpd) is expected


def test_the_npa_threshold_is_the_documented_ninety_days():
    assert NPA_THRESHOLD_DAYS == 90
    assert classify(NPA_THRESHOLD_DAYS) is SmaState.SMA_2
    assert classify(NPA_THRESHOLD_DAYS + 1) is SmaState.NPA


# --- revolving is a different measure ---------------------------------------

def test_revolving_never_returns_sma_0():
    """The framework defines no SMA-0 equivalent for revolving facilities."""
    assert all(
        classify_revolving(d) is not SmaState.SMA_0
        for d in range(0, 200)
    )


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, SmaState.STANDARD),
        (30, SmaState.STANDARD),
        (31, SmaState.SMA_1),
        (60, SmaState.SMA_1),
        (61, SmaState.SMA_2),
        (90, SmaState.SMA_2),
        (91, SmaState.NPA),
    ],
)
def test_revolving_band_boundaries(days: int, expected: SmaState):
    assert classify_revolving(days) is expected


# --- ordering ---------------------------------------------------------------

def test_states_are_ordered_by_severity():
    ladder = [
        SmaState.STANDARD, SmaState.SMA_0,
        SmaState.SMA_1, SmaState.SMA_2, SmaState.NPA,
    ]
    assert ladder == sorted(ladder)
    assert SmaState.SMA_2 > SmaState.SMA_0
    assert SmaState.STANDARD < SmaState.NPA


def test_only_standard_is_unstressed():
    assert SmaState.STANDARD.is_stressed is False
    assert all(
        s.is_stressed for s in SmaState if s is not SmaState.STANDARD
    )


# --- trajectory -------------------------------------------------------------

def test_days_until_the_next_downgrade():
    assert days_until(0, SmaState.SMA_0) == 1
    assert days_until(0, SmaState.SMA_1) == 31
    assert days_until(20, SmaState.SMA_1) == 11
    assert days_until(45, SmaState.SMA_2) == 16
    assert days_until(0, SmaState.NPA) == 91


def test_days_until_a_state_already_reached_is_none():
    assert days_until(45, SmaState.SMA_0) is None
    assert days_until(45, SmaState.SMA_1) is None
    assert days_until(200, SmaState.NPA) is None


def test_classification_reports_its_own_next_step():
    a = AssetClassification.of(20)
    assert a.state is SmaState.SMA_0
    assert a.next_state is SmaState.SMA_1
    assert a.days_to_next_downgrade == 11


def test_an_npa_has_nowhere_further_to_fall():
    a = AssetClassification.of(200)
    assert a.state is SmaState.NPA
    assert a.next_state is None
    assert a.days_to_next_downgrade is None


def test_the_circular_caveat_travels_with_the_classification():
    """The caveat is data, not a docstring nobody renders."""
    rendered = AssetClassification.of(10).render()
    assert "verified" in rendered["verify_against_circular"].lower()
    assert "CLAIMS_REGISTER" in rendered["verify_against_circular"]


# --- the bridge -------------------------------------------------------------

def test_behaviour_moving_while_the_account_is_standard_is_acting_early():
    """The window the whole system exists to act in."""
    gap = SupervisoryGap("AT_RISK", AssetClassification.of(0))
    assert gap.acting_early is True
    assert gap.missed is False
    assert gap.lead > 0


def test_an_overdue_account_the_behavioural_machinery_never_flagged_is_a_miss():
    """Surfaced rather than hidden — a negative lead is a real failure."""
    gap = SupervisoryGap("STABLE", AssetClassification.of(45))
    assert gap.missed is True
    assert gap.acting_early is False
    assert gap.lead < 0


def test_a_stable_customer_with_a_clean_account_is_neither():
    gap = SupervisoryGap("STABLE", AssetClassification.of(0))
    assert gap.acting_early is False
    assert gap.missed is False
    assert gap.lead == 0


def test_an_unknown_behavioural_state_is_treated_as_no_concern():
    """Fail closed: an unmapped state must not manufacture a lead."""
    gap = SupervisoryGap("NOT_A_STATE", AssetClassification.of(0))
    assert gap.behavioural_concern == 0
    assert gap.acting_early is False


def test_the_gap_renders_both_ladders_side_by_side():
    rendered = SupervisoryGap("WATCH", AssetClassification.of(0)).render()
    assert rendered["recovery_state"] == "WATCH"
    assert rendered["asset_classification"]["state"] == "STANDARD"
    assert rendered["acting_early"] is True
