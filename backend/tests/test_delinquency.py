"""Days past due, SMA banding, and the Recovery-Mode state that follows.

The behavioural promises asserted here:

* a customer who is paying is never flagged — the classifier must not
  manufacture arrears out of a mandate that presents a day or two early, or out
  of the horizon simply having ended;
* one missed instalment is SMA-0, two is SMA-1, three is SMA-2, and the
  boundaries are where the framing says they are;
* a restructured account is aged from its new mandate, so the arrears the
  restructuring resolved stop counting — otherwise granting relief would leave
  the customer classified as though it had never been granted;
* arrears activate Recovery Mode, and Recovery Mode only ever escalates.

Every figure comes from the synthetic generator (report §11.1), and the bands
themselves are framing to be verified against the current circular.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from artha.core.types import (
    Category,
    Direction,
    RecoveryState,
    RecurringSeries,
    SMAStage,
)
from artha.engines import delinquency
from artha.engines.delinquency import classify


# --- the banding itself -----------------------------------------------------


@pytest.mark.parametrize(
    ("dpd", "expected"),
    [
        (0, SMAStage.STANDARD),
        (1, SMAStage.SMA_0),
        (30, SMAStage.SMA_0),
        (31, SMAStage.SMA_1),
        (60, SMAStage.SMA_1),
        (61, SMAStage.SMA_2),
        (90, SMAStage.SMA_2),
        (91, SMAStage.NPA),
        (365, SMAStage.NPA),
    ],
)
def test_bands_break_where_the_framing_says_they_do(dpd, expected):
    assert classify(dpd) is expected


def test_negative_days_are_not_arrears():
    """A payment made early is not a payment missed."""
    assert classify(-5) is SMAStage.STANDARD


# --- classification from a transaction feed ---------------------------------


def _profile_of(engine, token):
    return engine.state(token).profile


def test_a_paying_customer_is_never_flagged(engine, ingest):
    """The horizon ending is not a missed instalment.

    This is the regression that matters most here: the generator used to window
    months from the as-of *day*, so the instalment due earlier in the current
    month was never emitted and every EMI-paying archetype read as one
    instalment past due before any arrears overlay was applied.
    """
    for key in ("salaried_stable", "salaried_volatile", "business", "injection"):
        token = ingest(key)
        state = engine.state(token)
        assert state.delinquency is not None
        assert state.delinquency.stage is SMAStage.STANDARD, (
            f"{key} was flagged {state.delinquency.stage.label} with "
            f"{state.delinquency.days_past_due} days past due"
        )


def test_no_mandate_means_no_classification(engine, ingest):
    """A customer with no instalment cannot be past due on one."""
    token = ingest("agricultural")          # no EMI in this archetype
    arrears = engine.state(token).delinquency
    assert arrears is not None
    assert arrears.stage is SMAStage.STANDARD
    assert arrears.mandate_series_id is None
    assert "No instalment mandate" in arrears.evidence[0]


@pytest.mark.parametrize(
    ("archetype", "stage", "missed"),
    [
        ("sma0_missed_once", SMAStage.SMA_0, 1),
        ("sma1_missed_twice", SMAStage.SMA_1, 2),
        ("sma2_missed_thrice", SMAStage.SMA_2, 3),
    ],
)
def test_missed_instalments_land_in_the_expected_band(
    engine, ingest, archetype, stage, missed
):
    token = ingest(archetype)
    arrears = engine.state(token).delinquency
    assert arrears is not None
    assert arrears.stage is stage
    assert arrears.missed_instalments == missed
    assert arrears.days_past_due > 0
    assert arrears.overdue_amount_paise == arrears.instalment_paise * missed
    assert engine.state(token).profile.sma_stage is stage


def test_the_stage_carries_its_evidence(engine, ingest):
    token = ingest("sma1_missed_twice")
    arrears = engine.state(token).delinquency
    assert arrears is not None
    assert arrears.oldest_unpaid_due is not None
    assert len(arrears.evidence) >= 3
    assert any(str(arrears.days_past_due) in e for e in arrears.evidence)
    # The caveat travels with the data, not only in a docstring.
    assert arrears.verify_against_circular is True
    assert any("circular" in e.lower() for e in arrears.evidence)


def test_a_restructured_account_is_aged_from_its_new_mandate(engine, ingest):
    """Granting relief must actually relieve the classification.

    The customer missed two instalments and was then restructured onto a smaller
    instalment on a later day. Ageing from the original mandate would report them
    deep in arrears on a loan that no longer exists, which would make the
    restructuring worthless to the customer and invisible to the bank.
    """
    token = ingest("recovery_restructured")
    arrears = engine.state(token).delinquency
    assert arrears is not None
    assert arrears.stage is SMAStage.STANDARD
    assert arrears.days_past_due == 0
    assert arrears.last_payment_on is not None


# --- part payments ----------------------------------------------------------


def test_a_part_payment_does_not_settle_an_instalment(as_of):
    """Paying half an EMI leaves the customer past due on the other half."""
    from artha.core.types import EnrichedTransaction, Transaction

    due_day = 5
    series = RecurringSeries(
        series_id="p:lender|EMI|DEBIT",
        category=Category.EMI,
        direction=Direction.DEBIT,
        median_amount_paise=10_000_00,
        period_days=30,
        day_of_month=due_day,
        last_seen=date(2026, 8, 5),
        occurrences=6,
        amount_volatility=0.0,
        evidence_dates=(date(2026, 7, 5), date(2026, 8, 5)),
    )

    def debit(on: date, paise: int) -> EnrichedTransaction:
        return EnrichedTransaction(
            txn=Transaction(
                txn_id=f"t-{on.isoformat()}", customer_token="tok_x",
                ts=__import__("datetime").datetime(on.year, on.month, on.day, 10, 0),
                amount_paise=-paise, narration="ACH D- LENDER-EMI",
            ),
            category=Category.EMI, series_id=series.series_id, is_recurring=True,
        )

    # July paid in full; August paid at a quarter, so August is outstanding.
    enriched = [debit(date(2026, 7, 5), 10_000_00), debit(date(2026, 8, 5), 2_500_00)]
    result = delinquency.assess([series], enriched, as_of=as_of)

    assert result.stage is not SMAStage.STANDARD
    assert result.oldest_unpaid_due == date(2026, 8, 5)


def test_a_debit_a_few_days_early_still_settles_its_instalment(as_of):
    """Mandates present ahead of the nominal date often enough to matter."""
    from artha.core.types import EnrichedTransaction, Transaction

    series = RecurringSeries(
        series_id="p:lender|EMI|DEBIT",
        category=Category.EMI, direction=Direction.DEBIT,
        median_amount_paise=5_000_00, period_days=30, day_of_month=10,
        last_seen=date(2026, 9, 8), occurrences=3,
        amount_volatility=0.0,
        evidence_dates=(date(2026, 7, 10), date(2026, 8, 9), date(2026, 9, 8)),
    )

    def debit(on: date) -> EnrichedTransaction:
        return EnrichedTransaction(
            txn=Transaction(
                txn_id=f"t-{on.isoformat()}", customer_token="tok_x",
                ts=__import__("datetime").datetime(on.year, on.month, on.day, 10, 0),
                amount_paise=-5_000_00, narration="ACH D- LENDER-EMI",
            ),
            category=Category.EMI, series_id=series.series_id, is_recurring=True,
        )

    enriched = [debit(date(2026, 7, 10)), debit(date(2026, 8, 9)), debit(date(2026, 9, 8))]
    result = delinquency.assess([series], enriched, as_of=as_of)
    assert result.stage is SMAStage.STANDARD
    assert result.missed_instalments == 0


# --- recovery activation ----------------------------------------------------


def test_sma0_activates_at_risk(engine, ingest):
    token = ingest("sma0_missed_once")
    assert engine.recovery.get(token).state is RecoveryState.AT_RISK


@pytest.mark.parametrize("archetype", ["sma1_missed_twice", "sma2_missed_thrice"])
def test_two_or_more_missed_instalments_activate_recovery(engine, ingest, archetype):
    token = ingest(archetype)
    record = engine.recovery.get(token)
    assert record.state is RecoveryState.RECOVERY
    assert record.suppresses_selling


def test_recovery_activation_is_logged_with_its_evidence(engine, ingest):
    from artha.audit.log import RecordType

    token = ingest("sma2_missed_thrice")
    transitions = [
        r for r in engine.audit.for_customer(token)
        if r.record_type is RecordType.RECOVERY_TRANSITION
    ]
    assert transitions, "arrears must log the Recovery-Mode transition they caused"
    payload = transitions[0].payload
    assert payload["trigger"] == "ARREARS"
    assert payload["sma_stage"] == SMAStage.SMA_2.value
    assert payload["evidence"]


def test_arrears_never_de_escalate_an_existing_state(engine, ingest):
    """A standard account does not pull a watched customer back to STABLE."""
    token = ingest("salaried_stable")
    engine.recovery.transition(
        token, RecoveryState.WATCH, reason="test", evidence=("test",)
    )
    # Re-ingesting a customer who is not in arrears must leave WATCH alone.
    state = engine.state(token)
    engine.ingest(token, state.transactions, balance_paise=state.profile.balance_paise)
    assert engine.recovery.get(token).state is RecoveryState.WATCH


def test_an_account_in_recovery_is_never_sold_to(engine, ingest, as_of):
    """Report §9.3 — the defining safeguard."""
    token = ingest("sma2_missed_thrice")
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.decision.offer is None
    assert bundle.decision.outcome.value in {"SUPPRESS", "PROTECT", "VERIFY"}


def test_the_decision_records_the_stage_it_was_taken_under(engine, ingest, as_of):
    token = ingest("sma1_missed_twice")
    decision = engine.decide(token, as_of=as_of).decision
    assert decision.sma_stage is SMAStage.SMA_1
    assert decision.days_past_due > 0
    rendered = decision.render_regulator()
    assert rendered["sma_stage"] == SMAStage.SMA_1.value
    # And it survives the round trip the audit log depends on.
    from artha.core.decision import DecisionObject

    assert DecisionObject.from_regulator_rendering(rendered).sma_stage is SMAStage.SMA_1


def test_a_restructured_customer_can_be_placed_mid_plan(engine, ingest, as_of):
    """The demo bootstrap's seeding path, exercised without the API."""
    token = ingest("recovery_restructured")
    granted = as_of - timedelta(days=62)
    engine.recovery.transition(
        token, RecoveryState.RECOVERY,
        reason="Restructuring granted for borrower financial difficulty",
        evidence=("two instalments missed before the plan",), at=granted,
    )
    record = engine.recovery.get(token)
    record.plan_started = granted
    record.plan_honoured_since = granted

    # Still inside the stabilisation window, so personalisation stays suppressed.
    assert engine.recovery.maybe_restore(token, as_of=as_of).state is RecoveryState.RECOVERY
    # And past it, the customer is restored rather than left there indefinitely.
    later = granted + timedelta(days=91)
    assert engine.recovery.maybe_restore(token, as_of=later).state is RecoveryState.STABLE
