"""Build a consent-scoped :class:`CustomerProfile` from enriched history.

This is the boundary the engines sit behind. They receive a profile and never
reach past it to raw transactions, which is what makes the consent scoping in
:mod:`artha.features.store` enforceable rather than aspirational: if a purpose
is revoked, the feature is absent from the profile and the engine cannot use
what it cannot see.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..core.types import (
    Category,
    ChannelSegment,
    CustomerProfile,
    Direction,
    FinancialPosture,
    IncomeType,
    RecoveryState,
)
from ..ontology.enrich import (
    EnrichmentResult,
    monthly_discretionary_paise,
)


def build_profile(
    customer_token: str,
    enrichment: EnrichmentResult,
    *,
    balance_paise: int,
    language: str = "hi",
    channel_segment: ChannelSegment = ChannelSegment.APP_NATIVE,
    recovery_state: RecoveryState = RecoveryState.STABLE,
    age: int | None = None,
    dependants: int = 0,
    has_term_cover: bool = False,
    has_health_cover: bool = False,
    credit_utilisation: float = 0.0,
    bureau_score: int | None = None,
    thin_file: bool = False,
    district: str = "",
    is_rural: bool = False,
    employer_id: str | None = None,
    tenure_with_bank_months: int = 0,
    on_time_emi_streak: int = 0,
    as_of: date | None = None,
) -> CustomerProfile:
    income = enrichment.income
    monthly_income = enrichment.monthly_income_paise
    committed = enrichment.monthly_committed_outflow_paise
    existing_emi = enrichment.existing_emi_paise
    discretionary = monthly_discretionary_paise(enrichment.enriched)
    income_day, income_day_dispersion = observed_income_day(enrichment.enriched)

    return CustomerProfile(
        customer_token=customer_token,
        language=language,
        channel_segment=channel_segment,
        income_type=income.income_type,
        income_type_confidence=income.confidence,
        income_type_overridden=income.overridden,
        posture=infer_posture(monthly_income, committed, existing_emi, balance_paise, credit_utilisation),
        recovery_state=recovery_state,
        balance_paise=balance_paise,
        monthly_income_paise=monthly_income,
        income_volatility=income.features.get("income_amount_cv", 0.0),
        monthly_committed_outflow_paise=max(committed - existing_emi, 0),
        monthly_discretionary_paise=discretionary,
        existing_emi_paise=existing_emi,
        age=age,
        dependants=dependants,
        has_term_cover=has_term_cover,
        has_health_cover=has_health_cover,
        credit_utilisation=credit_utilisation,
        bureau_score=bureau_score,
        thin_file=thin_file,
        district=district,
        is_rural=is_rural,
        employer_id=employer_id,
        series=tuple(enrichment.series),
        income_day_of_month=income_day,
        income_day_dispersion=income_day_dispersion,
        tenure_with_bank_months=tenure_with_bank_months,
        on_time_emi_streak=on_time_emi_streak,
    )


def infer_posture(
    monthly_income: int,
    committed: int,
    existing_emi: int,
    balance: int,
    utilisation: float,
) -> FinancialPosture:
    """Map cash-flow shape onto the five postures of report §7.3.

    Segments inform priors and populate fairness slices; they never decide.
    The posture is used to explain a decision and to route Recovery Mode, not
    to approve or refuse one — that separation is what stops a segment becoming
    a silent approval rule (§7.3).
    """
    if monthly_income <= 0:
        return FinancialPosture.STEADY

    oti = existing_emi / monthly_income
    surplus = (monthly_income - committed) / monthly_income
    months_of_cover = balance / max(committed, 1)

    if oti > 0.45 or utilisation > 0.80:
        return FinancialPosture.OVER_EXTENDED
    if oti > 0.28 or utilisation > 0.55:
        return FinancialPosture.LEVERAGED
    if months_of_cover >= 2.0 and surplus > 0.35:
        return FinancialPosture.BUFFER_BUILDING
    return FinancialPosture.STEADY


#: A debit may legitimately land a day or two either side of its nominal due
#: date — a weekend, a holiday, a mandate presented early. Treating that as a
#: default would manufacture delinquency out of ordinary settlement timing.
EMI_MATCH_WINDOW_DAYS = 3


def last_due_date(day_of_month: int, on_or_before: date) -> date:
    """The most recent monthly due date at or before ``on_or_before``.

    Clamped to the length of the month, so a due date on the 31st does not
    vanish in February — it falls on the 28th or 29th instead.
    """
    import calendar

    year, month = on_or_before.year, on_or_before.month
    day = min(day_of_month, calendar.monthrange(year, month)[1])
    if on_or_before.day < day:
        month -= 1
        if month < 1:
            month, year = 12, year - 1
        day = min(day_of_month, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_past_due(
    profile: CustomerProfile, enriched, *, as_of: date
) -> int:
    """Days past due on the customer's EMI, observed from the transactions.

    This is the input to supervisory asset classification
    (``core/asset_class.py``), and the reason that module is not an orphan: the
    system previously had no notion of days past due at all, so it could compute
    a behavioural state and had nothing to compare it against.

    The measure is deliberately conservative. A payment is treated as made if a
    matching EMI debit is seen anywhere from ``EMI_MATCH_WINDOW_DAYS`` before the
    due date onwards, and a customer with no detected EMI series is not past due
    on a loan they may not have. Both defaults fail *towards* Standard, because
    manufacturing a delinquency is a worse error here than missing one — a
    wrongly classified account changes how a real person is contacted.
    """
    emi_series = [
        s for s in profile.series
        if s.direction is Direction.DEBIT
        and s.category is Category.EMI
        and s.day_of_month
    ]
    if not emi_series:
        return 0

    last_observed = max((e.txn.value_date for e in enriched), default=None)
    if last_observed is None:
        return 0

    worst = 0
    for series in emi_series:
        due = last_due_date(series.day_of_month, as_of)

        # Non-payment can only be asserted where payment had a fair chance to be
        # observed. If the transaction feed stops at or near the due date, the
        # absence of a debit is missing data, not a missed payment — and a feed
        # that lags is the ordinary case, not the exception. Without this guard
        # the function reports a healthy customer as SMA-0 purely because their
        # history ended a few days early.
        if last_observed < due + timedelta(days=EMI_MATCH_WINDOW_DAYS):
            continue

        window_opens = due - timedelta(days=EMI_MATCH_WINDOW_DAYS)
        paid = any(
            e.series_id == series.series_id and e.txn.value_date >= window_opens
            for e in enriched
        )
        if paid:
            continue
        worst = max(worst, (as_of - due).days)
    return max(worst, 0)


def income_arrival_day(profile: CustomerProfile) -> int | None:
    """The day of month on which income actually lands.

    The Profitability Engine places the EMI date relative to this, and the
    Intervention Ladder's cheapest rung is defined by it (report §5.3).
    """
    from ..core.types import INCOME_CATEGORIES

    candidates = [
        s for s in profile.series
        if s.direction is Direction.CREDIT
        and s.category in INCOME_CATEGORIES
        and s.day_of_month
    ]
    if candidates:
        dominant = max(candidates, key=lambda s: s.median_amount_paise)
        return dominant.day_of_month

    # No clean series — fall back to the observed median day. An irregular
    # payroll is the case where date alignment helps most, so returning None
    # here would withhold the cheapest intervention from the customer with the
    # strongest claim on it.
    return profile.income_day_of_month


def is_income_shaped_for_monthly_emi(profile: CustomerProfile) -> bool:
    """Whether a fixed monthly EMI suits this income at all.

    An agricultural borrower with two harvests a year does not have a monthly
    repayment capacity, and quietly giving them one is how a performing loan
    becomes a stressed one. Report §6.1 routes these to a facility whose
    repayment is timed to harvest instead.
    """
    return profile.income_type not in {IncomeType.AGRICULTURAL, IncomeType.SEASONAL}


def observed_income_day(enriched) -> tuple[int | None, float]:
    """The day of month on which income actually lands, and how much it moves.

    Computed from the raw credits rather than from a detected recurring series.
    That distinction matters for precisely the customer this system exists to
    help: a small employer who pays late and erratically may never produce a
    clean monthly series, so periodicity detection returns nothing — and the
    Intervention Ladder's cheapest rung, shifting the EMI date to follow income,
    would be unavailable to the person who needs it most.

    A median over the observed days is defensible even when dispersion is high.
    The dispersion is returned alongside so the caller can say how firm the
    answer is rather than having to assume.
    """
    import statistics

    from ..core.types import INCOME_CATEGORIES, Direction

    days = [
        e.value_date.day for e in enriched
        if e.direction is Direction.CREDIT and e.category in INCOME_CATEGORIES
    ]
    if not days:
        return None, 0.0
    median_day = int(statistics.median(days))
    dispersion = float(statistics.pstdev(days)) if len(days) > 1 else 0.0
    return max(1, min(median_day, 28)), round(dispersion, 2)


def write_features(store, customer_token: str, profile: CustomerProfile, *, as_of=None) -> list[str]:
    """Publish a profile into the consent-scoped feature store.

    Only the declared features are written; anything the registry does not know
    about is reported back rather than silently stored, because a feature with
    no purpose attached is one that revocation cannot reach.
    """
    return store.put_many(
        customer_token,
        {
            "balance_paise": profile.balance_paise,
            "monthly_income_paise": profile.monthly_income_paise,
            "income_type": profile.income_type.value,
            "income_volatility": profile.income_volatility,
            "income_day_of_month": profile.income_day_of_month,
            "monthly_committed_outflow_paise": profile.monthly_committed_outflow_paise,
            "monthly_discretionary_paise": profile.monthly_discretionary_paise,
            "existing_emi_paise": profile.existing_emi_paise,
            "posture": profile.posture.value,
            "dependants": profile.dependants,
            "has_term_cover": profile.has_term_cover,
            "has_health_cover": profile.has_health_cover,
            "credit_utilisation": profile.credit_utilisation,
            "bureau_score": profile.bureau_score,
            "contactable": True,
        },
        as_of=as_of,
    )
