"""Recovery Mode — a reversible state machine.

Report §6.5 and Figure 8. Detected stress moves the customer into a state, not
onto a default list. The states and their contracts:

* ``STABLE``   — normal personalisation.
* ``WATCH``    — monitor, pause new credit, **do not contact**. The absence of
  contact is the point: a customer showing early indicators has not asked for
  help and may not need it.
* ``AT_RISK``  — options are offered, as a service.
* ``RECOVERY`` — all marketing suppressed, plan tracked, human support available.

Two rules that are easy to state and easy to omit:

1. **Declining is not a negative signal.** The customer may have income arriving
   from a source the bank cannot see. The choice is recorded, a "do not contact
   me about this" preference is honoured, and the case is re-assessed.
2. **Escalation to a human requires that assistance was offered and declined
   *and* that indicators continued to deteriorate** — and the banker then
   receives the underlying evidence rather than a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..core.revision import RevisionCounter
from ..core.types import RecoveryState

# How long a customer must honour a plan before personalisation is restored.
STABILISATION_DAYS = 90


@dataclass(frozen=True)
class RecoveryEvent:
    at: date
    from_state: RecoveryState
    to_state: RecoveryState
    reason: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    actor: str = "system"                    # system | banker | customer


@dataclass
class RecoveryRecord:
    customer_token: str
    state: RecoveryState = RecoveryState.STABLE
    since: date | None = None
    plan_started: date | None = None
    plan_honoured_since: date | None = None
    offers_declined: int = 0
    do_not_contact_families: set[str] = field(default_factory=set)
    history: list[RecoveryEvent] = field(default_factory=list)

    @property
    def suppresses_selling(self) -> bool:
        """AT_RISK and RECOVERY suppress selling in every product family.

        Report §9.3 calls this the defining safeguard of the system.
        """
        return self.state in {RecoveryState.AT_RISK, RecoveryState.RECOVERY}

    @property
    def suppresses_new_credit(self) -> bool:
        return self.state is not RecoveryState.STABLE

    @property
    def permits_contact(self) -> bool:
        """WATCH deliberately does not permit contact."""
        return self.state in {RecoveryState.STABLE, RecoveryState.AT_RISK, RecoveryState.RECOVERY}


class RecoveryMachine:
    """Transitions, each of which must carry a reason and its evidence."""

    def __init__(self) -> None:
        self._records: dict[str, RecoveryRecord] = {}
        # Bumped on every state change so a cached decision for this customer
        # can be recognised as stale however the change was made.
        self.revisions = RevisionCounter()

    def get(self, customer_token: str) -> RecoveryRecord:
        return self._records.setdefault(
            customer_token, RecoveryRecord(customer_token=customer_token)
        )

    def transition(
        self,
        customer_token: str,
        to_state: RecoveryState,
        *,
        reason: str,
        evidence: tuple[str, ...] = (),
        at: date | None = None,
        actor: str = "system",
    ) -> RecoveryRecord:
        at = at or date.today()
        record = self.get(customer_token)
        if record.state is to_state:
            return record

        record.history.append(
            RecoveryEvent(at, record.state, to_state, reason, evidence, actor)
        )
        self.revisions.bump(customer_token)
        record.state = to_state
        record.since = at
        if to_state is RecoveryState.RECOVERY:
            record.plan_started = at
            record.plan_honoured_since = at
        if to_state is RecoveryState.STABLE:
            record.plan_started = None
            record.plan_honoured_since = None
            record.offers_declined = 0
        return record

    def record_decline(
        self, customer_token: str, *, family: str | None = None, do_not_ask_again: bool = False
    ) -> RecoveryRecord:
        """A declined offer of assistance.

        Explicitly *not* a deterioration. Report §6.5: the customer may have
        income arriving from another source. Incrementing a counter here and
        treating it as risk elsewhere would quietly punish people for saying no.
        """
        record = self.get(customer_token)
        record.offers_declined += 1
        if do_not_ask_again and family:
            record.do_not_contact_families.add(family)
        self.revisions.bump(customer_token)
        return record

    def record_missed_commitment(self, customer_token: str, at: date | None = None) -> None:
        """Reset the stabilisation clock without changing state."""
        record = self.get(customer_token)
        record.plan_honoured_since = at or date.today()
        self.revisions.bump(customer_token)

    def maybe_restore(self, customer_token: str, *, as_of: date | None = None) -> RecoveryRecord:
        """Return to STABLE once a plan has been honoured for the defined period.

        Restoration is gradual by design — the customer returns to STABLE and
        personalisation resumes, rather than the system resuming where it left
        off with a queued backlog of offers.
        """
        as_of = as_of or date.today()
        record = self.get(customer_token)
        if record.state is not RecoveryState.RECOVERY or not record.plan_honoured_since:
            return record
        if as_of - record.plan_honoured_since >= timedelta(days=STABILISATION_DAYS):
            return self.transition(
                customer_token, RecoveryState.STABLE,
                reason=f"Plan honoured for {STABILISATION_DAYS} days",
                evidence=(f"plan_honoured_since={record.plan_honoured_since.isoformat()}",),
            )
        return record

    def should_escalate_to_human(self, customer_token: str, *, deteriorating: bool) -> bool:
        """Escalate only when assistance was offered, declined, and things got worse."""
        record = self.get(customer_token)
        return (
            deteriorating
            and record.offers_declined >= 1
            and record.state in {RecoveryState.AT_RISK, RecoveryState.RECOVERY}
        )


DEFAULT_MACHINE = RecoveryMachine()
