"""Days past due, and the Special Mention Account stage that follows from it.

Report §6.3 and §6.5. The Sentinel predicts stress *before* a payment is missed;
this module records what happened *after* one was. They are deliberately
separate: a prediction and an arrears fact have different evidential status, and
a system that blurs them cannot show a supervisor which of the two put a
customer into Recovery Mode.

The classification is a pure function of one number — days past due on the
currently active instalment mandate — and that number is derived from the
transaction feed rather than accepted from a caller, so the stage and the
evidence for it cannot drift apart.

REGULATORY STATUS: the day bands are the widely documented SMA framing listed in
``docs/CLAIMS_REGISTER.md`` §1. They are used here as *design framing* and are to
be cited from the current RBI circular before submission, not quoted from
memory. Two treatments in particular are flagged rather than assumed:

* the bands below apply to term loans; revolving facilities are classified on
  continuous excess over the sanctioned limit, which this module does not model;
* an account whose instalment mandate has been restructured is aged from the
  **new** mandate here (see :func:`active_mandate`). Re-ageing and upgrade after
  restructuring are governed by specific rules that must be read before this is
  presented as a compliant classification.

``VERIFY_AGAINST_CIRCULAR`` travels with every result so the caveat reaches the
console and the API rather than living only in this docstring.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..core.money import format_inr
from ..core.types import (
    Category,
    Direction,
    EnrichedTransaction,
    RecoveryState,
    RecurringSeries,
    SMAStage,
)

VERIFY_AGAINST_CIRCULAR = True

# Upper bound of each band, in days past due. The first band whose bound the
# DPD does not exceed wins; anything beyond the last is NPA.
SMA_BANDS: tuple[tuple[int, SMAStage], ...] = (
    (0, SMAStage.STANDARD),
    (30, SMAStage.SMA_0),
    (60, SMAStage.SMA_1),
    (90, SMAStage.SMA_2),
)

# How early a debit may land and still count as paying that instalment. Mandates
# present a day or two ahead of the nominal date often enough that a tighter
# window would manufacture arrears out of ordinary bank behaviour.
EARLY_PAYMENT_GRACE_DAYS = 4

# A part payment is not a payment. Anything below this share of the instalment
# leaves the instalment outstanding, which is the treatment that matters: a
# customer paying half an EMI is past due on the other half.
PART_PAYMENT_FLOOR = 0.60


@dataclass(frozen=True)
class DelinquencyResult:
    """One customer's arrears position, with the evidence that produced it."""

    stage: SMAStage
    days_past_due: int
    missed_instalments: int
    overdue_amount_paise: int
    oldest_unpaid_due: date | None
    last_payment_on: date | None
    instalment_paise: int
    mandate_series_id: str | None
    evidence: tuple[str, ...] = field(default_factory=tuple)
    verify_against_circular: bool = VERIFY_AGAINST_CIRCULAR

    @property
    def is_flagged(self) -> bool:
        return self.stage.is_flagged

    @property
    def recovery_state(self) -> RecoveryState | None:
        """The Recovery-Mode state this arrears position requires, if any.

        SMA-0 is one missed instalment: options are offered, as a service, which
        is exactly what AT_RISK means in report §6.5. From SMA-1 the customer is
        two instalments behind and selling stops in every family while a plan is
        tracked, which is RECOVERY. Returning ``None`` for a standard account
        leaves the state to the Sentinel rather than overriding it — an account
        that is current may still be predicted into stress.
        """
        if self.stage is SMAStage.SMA_0:
            return RecoveryState.AT_RISK
        if self.stage in {SMAStage.SMA_1, SMAStage.SMA_2, SMAStage.NPA}:
            return RecoveryState.RECOVERY
        return None

    def as_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "stage_label": self.stage.label,
            "days_past_due": self.days_past_due,
            "missed_instalments": self.missed_instalments,
            "overdue_amount": format_inr(self.overdue_amount_paise),
            "overdue_amount_paise": self.overdue_amount_paise,
            "oldest_unpaid_due": (
                self.oldest_unpaid_due.isoformat() if self.oldest_unpaid_due else None
            ),
            "last_payment_on": (
                self.last_payment_on.isoformat() if self.last_payment_on else None
            ),
            "instalment": format_inr(self.instalment_paise),
            "mandate_series_id": self.mandate_series_id,
            "evidence": list(self.evidence),
            "verify_against_circular": self.verify_against_circular,
        }


def classify(days_past_due: int) -> SMAStage:
    """Map days past due onto an SMA stage."""
    dpd = max(int(days_past_due), 0)
    for bound, stage in SMA_BANDS:
        if dpd <= bound:
            return stage
    return SMAStage.NPA


def active_mandate(series: Sequence[RecurringSeries]) -> RecurringSeries | None:
    """The instalment mandate the account is currently being paid under.

    A restructured loan appears in the feed as a *new* series — a different
    amount on a different day — running alongside the closed one. Classifying
    against the most recently seen series is what makes the arrears that the
    restructure resolved stop counting, which is the whole point of granting it.
    Ageing after restructuring is one of the treatments flagged in the module
    docstring for verification.
    """
    mandates = [
        s for s in series
        if s.direction is Direction.DEBIT and s.category is Category.EMI
    ]
    if not mandates:
        return None
    return max(mandates, key=lambda s: (s.last_seen, s.occurrences))


def assess(
    series: Sequence[RecurringSeries],
    enriched: Sequence[EnrichedTransaction],
    *,
    as_of: date | None = None,
) -> DelinquencyResult:
    """Derive days past due and the SMA stage from the transaction feed.

    Takes the detected series rather than a profile so the classification can be
    run while the profile is still being built, and so it stays testable without
    one.
    """
    as_of = as_of or date.today()
    mandate = active_mandate(series)
    if mandate is None:
        return DelinquencyResult(
            stage=SMAStage.STANDARD, days_past_due=0, missed_instalments=0,
            overdue_amount_paise=0, oldest_unpaid_due=None, last_payment_on=None,
            instalment_paise=0, mandate_series_id=None,
            evidence=("No instalment mandate detected in the transaction feed.",),
        )

    payments = _payments_for(mandate, enriched, as_of)
    schedule = _schedule(mandate, as_of, first_payment=min(payments) if payments else None)

    unpaid = [due for due in schedule if not _settled(due, payments, schedule)]
    last_payment = max(payments) if payments else None

    if not unpaid:
        return DelinquencyResult(
            stage=SMAStage.STANDARD, days_past_due=0, missed_instalments=0,
            overdue_amount_paise=0, oldest_unpaid_due=None,
            last_payment_on=last_payment,
            instalment_paise=mandate.median_amount_paise,
            mandate_series_id=mandate.series_id,
            evidence=(
                f"{len(schedule)} instalments of "
                f"{format_inr(mandate.median_amount_paise)} due since "
                f"{schedule[0].isoformat()}, all settled."
                if schedule else
                "Mandate detected but no instalment has fallen due yet.",
            ),
        )

    oldest = unpaid[0]
    dpd = (as_of - oldest).days
    stage = classify(dpd)
    overdue = mandate.median_amount_paise * len(unpaid)

    evidence = [
        f"Instalment of {format_inr(mandate.median_amount_paise)} due "
        f"{oldest.isoformat()} is unpaid as at {as_of.isoformat()} — {dpd} days past due.",
        f"{len(unpaid)} instalment(s) outstanding, {format_inr(overdue)} in arrears.",
        (
            f"Last instalment received {last_payment.isoformat()}."
            if last_payment else
            "No instalment received under this mandate."
        ),
        f"Classified {stage.label} on days past due; band to be verified against "
        f"the current RBI circular before use (report §11.2).",
    ]

    return DelinquencyResult(
        stage=stage,
        days_past_due=dpd,
        missed_instalments=len(unpaid),
        overdue_amount_paise=overdue,
        oldest_unpaid_due=oldest,
        last_payment_on=last_payment,
        instalment_paise=mandate.median_amount_paise,
        mandate_series_id=mandate.series_id,
        evidence=tuple(evidence),
    )


# --- helpers ----------------------------------------------------------------


def _payments_for(
    mandate: RecurringSeries, enriched: Sequence[EnrichedTransaction], as_of: date
) -> list[date]:
    """Dates on which this mandate was actually debited.

    Matched on the series id, so a restructured account is measured against its
    new mandate alone and the arrears the restructure resolved stop counting.
    Falling back to the EMI category only when *no* transaction carries the
    series id keeps the classifier working when recurrence detection was broken
    by the very run of missed months under examination, without letting a second
    live mandate's debits settle this one's instalments.
    """
    floor = int(mandate.median_amount_paise * PART_PAYMENT_FLOOR)
    candidates = [
        e for e in enriched
        if e.direction is Direction.DEBIT
        and e.value_date <= as_of
        and abs(e.amount_paise) >= floor
    ]
    matched = [e for e in candidates if e.series_id == mandate.series_id]
    if not matched:
        matched = [e for e in candidates if e.category is Category.EMI]
    dates = {e.value_date for e in matched}
    if not dates:
        dates.update(d for d in mandate.evidence_dates if d <= as_of)
    return sorted(dates)


def _schedule(
    mandate: RecurringSeries, as_of: date, *, first_payment: date | None
) -> list[date]:
    """Due dates under this mandate, from its first observed instalment to today.

    Bounded by the mandate's own history rather than by the loan's origination:
    the feed is the only evidence available, and inventing due dates that
    predate it would invent arrears with it.
    """
    start = first_payment or mandate.last_seen
    if mandate.period_days >= 28 and mandate.day_of_month:
        due = _on_day(start, mandate.day_of_month)
        if due < start - timedelta(days=EARLY_PAYMENT_GRACE_DAYS):
            due = _add_months(due, 1)
        out: list[date] = []
        step = 0
        while due <= as_of:
            out.append(due)
            step += 1
            due = _add_months(_on_day(start, mandate.day_of_month), step)
        return out

    period = max(mandate.period_days, 1)
    out = []
    due = start
    while due <= as_of:
        out.append(due)
        due = due + timedelta(days=period)
    return out


def _settled(due: date, payments: list[date], schedule: list[date]) -> bool:
    """Was there a debit that answers this instalment?

    The window runs from a few days before the due date to the day before the
    next one. Letting it run to the next due date instead would allow one debit
    to settle two instalments, which is how an account two months behind reads
    as current.
    """
    nxt = next((d for d in schedule if d > due), None)
    window_start = due - timedelta(days=EARLY_PAYMENT_GRACE_DAYS)
    window_end = (nxt - timedelta(days=1)) if nxt else date.max
    return any(window_start <= p <= window_end for p in payments)


def _on_day(d: date, day: int) -> date:
    import calendar

    day = max(1, min(int(day), calendar.monthrange(d.year, d.month)[1]))
    return date(d.year, d.month, day)


def _add_months(d: date, months: int) -> date:
    import calendar

    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
