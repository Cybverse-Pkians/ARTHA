"""Recurrence and drift detection.

Report §7.1 asks for periodicity detection with changepoint detection on the
amount–date series, and gives the reason in the rationale column: the result has
to be *interpretable*, because the supporting evidence dates must be showable to
a regulator. Every :class:`RecurringSeries` this module emits therefore carries
the dates that justify it.

Implemented on NumPy alone. A heavier time-series dependency would buy little
here — these series are short, sparse and dominated by calendar effects that
generic seasonality models handle worse than an explicit day-of-month rule.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np

from ..core.types import (
    COMMITTED_OUTFLOW_CATEGORIES,
    INCOME_CATEGORIES,
    Category,
    Direction,
    EnrichedTransaction,
    RecurringSeries,
)

# Periods we are willing to assert, in days, with the tolerance each allows.
_PERIOD_CANDIDATES: tuple[tuple[int, int, str], ...] = (
    (7, 2, "weekly"),
    (14, 3, "fortnightly"),
    (30, 5, "monthly"),
    (91, 12, "quarterly"),
    (182, 20, "half-yearly"),
    (365, 30, "annual"),
)

MIN_OCCURRENCES = 3


@dataclass(frozen=True)
class DriftResult:
    drifting: bool
    changepoint_index: int | None
    before_median: float
    after_median: float
    relative_shift: float


def detect_series(
    enriched: list[EnrichedTransaction],
    *,
    as_of: date | None = None,
    min_occurrences: int = MIN_OCCURRENCES,
) -> list[RecurringSeries]:
    """Group transactions into recurring series and characterise each.

    Grouping is by (counterparty key, category, direction). The counterparty key
    matters more than the amount: a rent that rises on renewal is still rent, and
    a salary that changes on promotion is still salary. Grouping on amount would
    silently split exactly the series whose changes are most interesting.
    """
    as_of = as_of or date.today()
    buckets: dict[tuple[str, Category, Direction], list[EnrichedTransaction]] = defaultdict(list)

    for e in enriched:
        key = e.counterparty_key or (e.merchant.merchant_id if e.merchant else None)
        if key is None:
            # Without a stable counterparty, fall back to category-level grouping
            # for the categories where that is still meaningful.
            if e.category not in COMMITTED_OUTFLOW_CATEGORIES | INCOME_CATEGORIES:
                continue
            key = f"c:{e.category.value}"
        buckets[(key, e.category, e.direction)].append(e)

    series: list[RecurringSeries] = []
    for (key, category, direction), items in buckets.items():
        if len(items) < min_occurrences:
            continue
        items.sort(key=lambda x: x.value_date)
        built = _build_series(key, category, direction, items, as_of)
        if built is not None:
            series.append(built)

    series.sort(key=lambda s: (s.direction is not Direction.CREDIT, -s.median_amount_paise))
    return series


def _build_series(
    key: str,
    category: Category,
    direction: Direction,
    items: list[EnrichedTransaction],
    as_of: date,
) -> RecurringSeries | None:
    dates = [e.value_date for e in items]
    amounts = np.array([abs(e.amount_paise) for e in items], dtype=float)
    gaps = np.diff(np.array([d.toordinal() for d in dates], dtype=float))
    if gaps.size == 0:
        return None

    period, label = _match_period(gaps)
    if period is None:
        return None

    median_amount = float(np.median(amounts))
    volatility = float(np.std(amounts) / median_amount) if median_amount > 0 else 0.0
    drift = detect_drift(amounts)

    day_of_month = None
    if period >= 28:
        days = np.array([d.day for d in dates])
        # Median rather than mode: month-end series legitimately land on 28-31,
        # and a mode would pick one of those arbitrarily.
        day_of_month = int(np.clip(np.median(days), 1, 28))

    return RecurringSeries(
        series_id=f"{key}|{category.value}|{direction.value}",
        category=category,
        direction=direction,
        median_amount_paise=int(round(median_amount)),
        period_days=period,
        day_of_month=day_of_month,
        last_seen=dates[-1],
        occurrences=len(items),
        amount_volatility=round(volatility, 4),
        evidence_dates=tuple(dates[-6:]),
        label=f"{label} {category.value.replace('_', ' ').title()}",
        drifting=drift.drifting,
    )


def _match_period(gaps: np.ndarray) -> tuple[int | None, str]:
    """Pick the period whose tolerance the observed gaps actually respect.

    Requires two thirds of gaps to fall inside the tolerance band. A looser rule
    turns any cluster of transactions into a "monthly" series, and a spurious
    recurring obligation is worse than a missed one — it inflates committed
    outflow and denies credit to someone who qualifies.
    """
    median_gap = float(np.median(gaps))
    best: tuple[int | None, str, float] = (None, "", 0.0)

    for period, tolerance, label in _PERIOD_CANDIDATES:
        if abs(median_gap - period) > tolerance:
            continue
        hit_rate = float(np.mean(np.abs(gaps - period) <= tolerance))
        if hit_rate >= 0.66 and hit_rate > best[2]:
            best = (period, label, hit_rate)

    return best[0], best[1]


def detect_drift(amounts: np.ndarray, *, min_shift: float = 0.12) -> DriftResult:
    """Single-changepoint detection by exhaustive split on the median.

    The series are short — typically six to twenty-four points — so scanning
    every split is both exact and cheap, and it avoids the tuning burden of a
    penalised method. Robust statistics throughout: one festival-month salary
    bonus must not read as a permanent raise.
    """
    n = amounts.size
    if n < 6:
        med = float(np.median(amounts)) if n else 0.0
        return DriftResult(False, None, med, med, 0.0)

    best_idx, best_shift = None, 0.0
    for i in range(3, n - 2):
        before = float(np.median(amounts[:i]))
        after = float(np.median(amounts[i:]))
        if before <= 0:
            continue
        shift = abs(after - before) / before
        if shift > best_shift:
            best_idx, best_shift = i, shift

    if best_idx is None or best_shift < min_shift:
        med = float(np.median(amounts))
        return DriftResult(False, None, med, med, round(best_shift, 4))

    return DriftResult(
        drifting=True,
        changepoint_index=best_idx,
        before_median=float(np.median(amounts[:best_idx])),
        after_median=float(np.median(amounts[best_idx:])),
        relative_shift=round(best_shift, 4),
    )


def next_due_date(series: RecurringSeries, after: date) -> date | None:
    """Project the next occurrence of a series.

    Used by the Moment Engine to see an obligation ending before it ends, and by
    the Profitability Engine to place an EMI date relative to income arrival.
    """
    from datetime import timedelta

    if series.period_days >= 28 and series.day_of_month:
        year, month = after.year, after.month
        if after.day >= series.day_of_month:
            month += 1
            if month > 12:
                month, year = 1, year + 1
        import calendar

        day = min(series.day_of_month, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    candidate = series.last_seen + timedelta(days=series.period_days)
    while candidate <= after:
        candidate += timedelta(days=series.period_days)
    return candidate


def income_series(series: list[RecurringSeries]) -> list[RecurringSeries]:
    return [s for s in series if s.direction is Direction.CREDIT and s.category in INCOME_CATEGORIES]


def obligation_series(series: list[RecurringSeries]) -> list[RecurringSeries]:
    return [
        s for s in series
        if s.direction is Direction.DEBIT and s.category in COMMITTED_OUTFLOW_CATEGORIES
    ]
