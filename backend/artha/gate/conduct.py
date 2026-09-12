"""Nudge budget and empathy calendar.

Report §5.2 and §9.3. Two of the six Gate checks, grouped because they answer
the same question from different directions: *is this a reasonable moment to
speak to this person at all?*

Neither is a model. Both are hard caps, because a frequency limit that a ranker
can bid its way past is not a limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from ..config import settings


@dataclass
class ContactRecord:
    customer_token: str
    contacts: list[tuple[date, str]] = field(default_factory=list)     # (date, family)

    def in_month(self, as_of: date) -> int:
        return sum(1 for d, _ in self.contacts if (d.year, d.month) == (as_of.year, as_of.month))

    def last_for_family(self, family: str) -> date | None:
        dates = [d for d, f in self.contacts if f == family]
        return max(dates) if dates else None


class NudgeBudget:
    """Contacts per month, plus a per-product cooldown."""

    def __init__(
        self, per_month: int | None = None, cooldown_days: int | None = None
    ) -> None:
        self.per_month = per_month or settings.nudge_budget_per_month
        self.cooldown_days = cooldown_days or settings.product_cooldown_days
        self._records: dict[str, ContactRecord] = {}

    def get(self, customer_token: str) -> ContactRecord:
        return self._records.setdefault(
            customer_token, ContactRecord(customer_token=customer_token)
        )

    def remaining(self, customer_token: str, as_of: date) -> int:
        return max(self.per_month - self.get(customer_token).in_month(as_of), 0)

    def budget_available(self, customer_token: str, as_of: date) -> bool:
        return self.remaining(customer_token, as_of) > 0

    def cooldown_active(self, customer_token: str, family: str, as_of: date) -> bool:
        last = self.get(customer_token).last_for_family(family)
        return bool(last and (as_of - last) < timedelta(days=self.cooldown_days))

    def cooldown_remaining_days(self, customer_token: str, family: str, as_of: date) -> int:
        last = self.get(customer_token).last_for_family(family)
        if not last:
            return 0
        return max(self.cooldown_days - (as_of - last).days, 0)

    def record_contact(self, customer_token: str, family: str, as_of: date) -> None:
        self.get(customer_token).contacts.append((as_of, family))


class LifeEvent(str, Enum):
    """Events during which no product is offered (report §5.2).

    Detection is deliberately conservative and every entry is reversible: a
    false positive here costs the bank one suppressed offer, while a false
    negative means contacting a bereaved customer about a credit card.
    """

    BEREAVEMENT = "BEREAVEMENT"
    JOB_LOSS = "JOB_LOSS"
    EXAMINATION_SEASON = "EXAMINATION_SEASON"
    MEDICAL_EVENT = "MEDICAL_EVENT"
    NATURAL_DISASTER = "NATURAL_DISASTER"


@dataclass(frozen=True)
class EmpathyWindow:
    event: LifeEvent
    start: date
    end: date
    evidence: str = ""

    def covers(self, as_of: date) -> bool:
        return self.start <= as_of <= self.end


class EmpathyCalendar:
    """Per-customer suppression windows, plus seasonal ones."""

    def __init__(self) -> None:
        self._windows: dict[str, list[EmpathyWindow]] = {}

    def add(
        self,
        customer_token: str,
        event: LifeEvent,
        *,
        start: date,
        days: int = 45,
        evidence: str = "",
    ) -> EmpathyWindow:
        window = EmpathyWindow(event, start, start + timedelta(days=days), evidence)
        self._windows.setdefault(customer_token, []).append(window)
        return window

    def active(self, customer_token: str, as_of: date) -> EmpathyWindow | None:
        for window in self._windows.get(customer_token, []):
            if window.covers(as_of):
                return window
        # Examination season: a household with school fees is under a different
        # kind of pressure in March, and it applies to the population, not to a
        # detected individual event.
        if as_of.month == 3:
            return EmpathyWindow(
                LifeEvent.EXAMINATION_SEASON,
                date(as_of.year, 3, 1), date(as_of.year, 3, 31),
                evidence="Board examination season (population-level window).",
            )
        return None


DEFAULT_BUDGET = NudgeBudget()
DEFAULT_CALENDAR = EmpathyCalendar()
