"""The behavioural state machine: reversibility, hysteresis, and reaching RECOVERY.

Three defects this covers, all of which made the module docstring's "reversible
state machine" untrue at runtime:

* ``maybe_restore``, ``record_missed_commitment``, ``should_escalate_to_human``,
  ``permits_contact`` and ``suppresses_new_credit`` had no callers outside the
  module, so ``STABILISATION_DAYS`` was dead code and nobody ever left WATCH.
* The only automated transition chose between WATCH and AT_RISK and never
  returned anyone to STABLE.
* A bare threshold re-evaluated every decision made a customer near it oscillate.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from artha.core.types import RecoveryState
from artha.gate.recovery import (
    ENTER_AT_RISK,
    ENTER_WATCH,
    EXIT_AT_RISK,
    MIN_DWELL_DAYS,
    STABILISATION_DAYS,
    RecoveryMachine,
    target_state,
)

AS_OF = date(2026, 9, 12)


@pytest.fixture
def machine() -> RecoveryMachine:
    return RecoveryMachine()


# --- hysteresis -------------------------------------------------------------

def test_entry_and_exit_thresholds_are_not_the_same_number():
    """A single threshold is what makes a state machine oscillate."""
    assert EXIT_AT_RISK < ENTER_AT_RISK


def test_escalation_is_immediate():
    """Deterioration should not have to wait out a dwell period."""
    assert target_state(
        RecoveryState.STABLE, ENTER_AT_RISK, dwelt_long_enough=False
    ) is RecoveryState.AT_RISK


def test_a_customer_between_the_thresholds_does_not_move():
    """The gap between entry and exit is the anti-thrash band."""
    between = (ENTER_AT_RISK + EXIT_AT_RISK) / 2
    assert target_state(
        RecoveryState.AT_RISK, between, dwelt_long_enough=True
    ) is RecoveryState.AT_RISK


def test_de_escalation_requires_the_dwell_period():
    assert target_state(
        RecoveryState.AT_RISK, 0.0, dwelt_long_enough=False
    ) is RecoveryState.AT_RISK
    assert target_state(
        RecoveryState.AT_RISK, 0.0, dwelt_long_enough=True
    ) is RecoveryState.WATCH


def test_de_escalation_steps_down_one_level_at_a_time():
    """Restoration is gradual by design; AT_RISK does not jump to STABLE."""
    assert target_state(
        RecoveryState.AT_RISK, 0.0, dwelt_long_enough=True
    ) is RecoveryState.WATCH
    assert target_state(
        RecoveryState.WATCH, 0.0, dwelt_long_enough=True
    ) is RecoveryState.STABLE


def test_a_stable_customer_reaches_watch_before_at_risk():
    assert target_state(
        RecoveryState.STABLE, ENTER_WATCH, dwelt_long_enough=True
    ) is RecoveryState.WATCH


def test_indicators_never_move_a_customer_out_of_recovery():
    """A plan ends by being honoured or missed, not because a score moved."""
    for uplift in (0.0, 0.02, 0.5):
        assert target_state(
            RecoveryState.RECOVERY, uplift, dwelt_long_enough=True
        ) is RecoveryState.RECOVERY


# --- RECOVERY is reachable --------------------------------------------------

def test_accepting_an_offer_enters_recovery(machine: RecoveryMachine):
    """Previously set only in the test suite and the debug harness."""
    machine.transition(
        "c1", RecoveryState.AT_RISK, reason="stress", at=AS_OF
    )
    record = machine.accept_plan("c1", at=AS_OF, family="LOAN")
    assert record.state is RecoveryState.RECOVERY
    assert record.plan_started == AS_OF
    assert record.plan_honoured_since == AS_OF


def test_the_acceptance_is_attributed_to_the_customer(machine: RecoveryMachine):
    machine.accept_plan("c1", at=AS_OF)
    assert machine.get("c1").history[-1].actor == "customer"


def test_recovery_suppresses_all_selling(machine: RecoveryMachine):
    machine.accept_plan("c1", at=AS_OF)
    assert machine.get("c1").suppresses_selling is True


# --- there is a way out -----------------------------------------------------

def test_a_plan_honoured_long_enough_restores_personalisation(machine: RecoveryMachine):
    machine.accept_plan("c1", at=AS_OF)
    later = AS_OF + timedelta(days=STABILISATION_DAYS)
    record = machine.maybe_restore("c1", as_of=later)
    assert record.state is RecoveryState.STABLE
    assert record.plan_started is None


def test_a_plan_not_yet_honoured_long_enough_does_not_restore(machine: RecoveryMachine):
    machine.accept_plan("c1", at=AS_OF)
    early = AS_OF + timedelta(days=STABILISATION_DAYS - 1)
    assert machine.maybe_restore("c1", as_of=early).state is RecoveryState.RECOVERY


def test_a_missed_commitment_resets_the_stabilisation_clock(machine: RecoveryMachine):
    machine.accept_plan("c1", at=AS_OF)
    missed = AS_OF + timedelta(days=60)
    machine.record_missed_commitment("c1", at=missed)
    # 90 days after the original start is no longer enough.
    assert machine.maybe_restore(
        "c1", as_of=AS_OF + timedelta(days=STABILISATION_DAYS)
    ).state is RecoveryState.RECOVERY
    assert machine.maybe_restore(
        "c1", as_of=missed + timedelta(days=STABILISATION_DAYS)
    ).state is RecoveryState.STABLE


# --- dwell ------------------------------------------------------------------

def test_days_in_state_counts_from_the_last_transition(machine: RecoveryMachine):
    machine.transition("c1", RecoveryState.WATCH, reason="stress", at=AS_OF)
    assert machine.days_in_state("c1", as_of=AS_OF) == 0
    assert machine.days_in_state("c1", as_of=AS_OF + timedelta(days=20)) == 20


def test_a_customer_who_never_transitioned_counts_as_having_dwelt(machine: RecoveryMachine):
    """No history means indefinitely STABLE, not freshly arrived."""
    assert machine.days_in_state("never-seen", as_of=AS_OF) >= MIN_DWELL_DAYS


# --- end to end -------------------------------------------------------------

def test_repeated_decisions_at_a_steady_uplift_do_not_thrash(engine, ingest, as_of):
    """Each flip would write an audit record and flicker the customer's offers."""
    from artha.audit.log import RecordType

    token = ingest("stressed")
    for _ in range(6):
        engine.decide(token, as_of=as_of)

    transitions = [
        r for r in engine.audit.records
        if r.record_type is RecordType.RECOVERY_TRANSITION
        and r.customer_token == token
    ]
    assert len(transitions) <= 1, f"state thrashed {len(transitions)} times"


def test_the_state_machine_is_evaluated_even_when_nothing_is_wrong(
    engine, ingest, as_of, machine
):
    """A WATCH customer must be reconsidered on a healthy decision too.

    Evaluating the state only inside the distress branch is what made the
    machine one-way: the code that could release a customer required them to
    still be stressed.
    """
    token = ingest("salaried_stable")
    engine.recovery.transition(
        token, RecoveryState.WATCH, reason="seeded", at=as_of - timedelta(days=60)
    )
    engine.decide(token, as_of=as_of)
    assert engine.recovery.get(token).state is RecoveryState.STABLE
