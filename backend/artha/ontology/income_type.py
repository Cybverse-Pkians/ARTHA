"""Income typing — the single label that reconfigures every downstream model.

Report §4.2 states the stakes: "a farmer with no income for four months is
normal, whereas a salaried customer showing the same pattern is in crisis."
Report §5.1 and §11.3 then name the corresponding failure: misclassifying
seasonal income as irregular would wrongly deny credit to precisely the
customers this problem statement is concerned with.

Two consequences are built into this module rather than documented beside it.

1. **The human override is a first-class input, not an afterthought.** It is a
   parameter of the classify call, it wins unconditionally, and it is recorded
   as the method so the decision log shows a human made the call.

2. **Seasonality is checked before irregularity.** The ordering is deliberate.
   An income profile that looks erratic against a salaried template is tested
   for an agricultural or seasonal explanation *first*, and only falls through
   to "volatile" when no such structure is present.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..core.types import (
    Category,
    Direction,
    EnrichedTransaction,
    IncomeType,
    RecurringSeries,
)

# Months in which Indian agricultural proceeds typically land: the kharif
# marketing window (Oct–Jan) and the rabi window (Mar–May).
_AGRI_HARVEST_MONTHS = frozenset({10, 11, 12, 1, 3, 4, 5})


@dataclass(frozen=True)
class IncomeTypeResult:
    income_type: IncomeType
    confidence: float
    method: str                                   # rules | model | override
    evidence: tuple[str, ...] = field(default_factory=tuple)
    features: dict[str, float] = field(default_factory=dict)
    overridden: bool = False


@dataclass(frozen=True)
class IncomeFeatures:
    """Interpretable features. Each one can be read aloud in a review meeting,
    which is the practical test of whether it belongs in a credit model."""

    months_observed: float
    n_income_txns: int
    n_income_counterparties: int
    has_monthly_salary_series: float
    salary_day_regularity: float          # 1.0 == lands on the same day every month
    income_amount_cv: float               # coefficient of variation
    zero_income_month_share: float
    month_concentration: float            # HHI over calendar months, 0..1
    harvest_month_share: float
    agri_share: float
    gig_share: float
    business_share: float
    salary_share: float
    govt_benefit_share: float
    credits_per_month: float
    income_runs: float = 0.0              # distinct bursts of income-bearing months
    trailing_zero_months: float = 0.0     # income-less months at the end of the window

    def as_dict(self) -> dict[str, float]:
        return {
            "months_observed": self.months_observed,
            "n_income_txns": float(self.n_income_txns),
            "n_income_counterparties": float(self.n_income_counterparties),
            "has_monthly_salary_series": self.has_monthly_salary_series,
            "salary_day_regularity": self.salary_day_regularity,
            "income_amount_cv": self.income_amount_cv,
            "zero_income_month_share": self.zero_income_month_share,
            "month_concentration": self.month_concentration,
            "harvest_month_share": self.harvest_month_share,
            "agri_share": self.agri_share,
            "gig_share": self.gig_share,
            "business_share": self.business_share,
            "salary_share": self.salary_share,
            "govt_benefit_share": self.govt_benefit_share,
            "credits_per_month": self.credits_per_month,
            "income_runs": self.income_runs,
            "trailing_zero_months": self.trailing_zero_months,
        }


def extract_features(
    enriched: list[EnrichedTransaction],
    series: list[RecurringSeries],
    *,
    as_of: date | None = None,
) -> IncomeFeatures:
    as_of = as_of or date.today()
    credits = [
        e for e in enriched
        if e.direction is Direction.CREDIT and e.category in {
            Category.SALARY, Category.GIG_PAYOUT, Category.AGRI_PROCEEDS,
            Category.BUSINESS_RECEIPTS, Category.GOVT_BENEFIT, Category.REMITTANCE_IN,
        }
    ]
    if not credits:
        return IncomeFeatures(0, 0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    dates = [e.value_date for e in credits]
    amounts = np.array([abs(e.amount_paise) for e in credits], dtype=float)

    # The observation window is the span of *all* activity, not of income alone.
    #
    # Bounding it by the first and last income credit makes a trailing income
    # gap structurally invisible — the window ends at the last salary, so there
    # is never anything after it. That is precisely the gap that distinguishes a
    # job loss from a season, so the window has to extend to the present.
    all_dates = [e.value_date for e in enriched] or dates
    window_start = min(min(all_dates), min(dates))
    window_end = max(max(all_dates), max(dates), as_of)
    span_days = max((window_end - window_start).days, 1)
    months_observed = max(span_days / 30.44, 1.0)

    total = float(amounts.sum()) or 1.0

    def share(cat: Category) -> float:
        return float(sum(abs(e.amount_paise) for e in credits if e.category is cat) / total)

    # Month coverage — how much of the observed span produced no income at all.
    month_sequence = [(d.year, d.month) for d in _months_between(window_start, window_end)]
    income_months = {(d.year, d.month) for d in dates}
    zero_share = 1.0 - (len(income_months) / max(len(month_sequence), 1))

    # Bursts of income-bearing months, and how many income-less months sit at the
    # end of the window.
    #
    # These two features separate a seasonal profile from a job loss, which
    # report §11.3 names as a top limitation: both show long income-less
    # stretches. Seasonality *repeats* — two or more separate bursts — while a
    # job loss is a single burst followed by a gap that is still open at the
    # right-hand edge of the data. Without this distinction the system denies
    # credit to a farmer for looking like a redundancy.
    flags = [1 if m in income_months else 0 for m in month_sequence]
    income_runs = sum(
        1 for i, v in enumerate(flags) if v == 1 and (i == 0 or flags[i - 1] == 0)
    )
    trailing = 0
    for v in reversed(flags):
        if v == 1:
            break
        trailing += 1

    # Concentration across calendar months (Herfindahl, normalised).
    per_month = Counter()
    for e in credits:
        per_month[e.value_date.month] += abs(e.amount_paise)
    p = np.array(list(per_month.values()), dtype=float)
    p = p / p.sum()
    hhi = float((p ** 2).sum())
    concentration = float(np.clip((hhi - 1 / 12) / (1 - 1 / 12), 0.0, 1.0))

    harvest_amount = sum(abs(e.amount_paise) for e in credits if e.value_date.month in _AGRI_HARVEST_MONTHS)

    salary_series = [
        s for s in series
        if s.direction is Direction.CREDIT and s.category is Category.SALARY and s.period_days >= 28
    ]
    has_monthly_salary = 1.0 if salary_series else 0.0

    if salary_series:
        days = [d.day for s in salary_series for d in s.evidence_dates]
        day_regularity = float(np.clip(1.0 - (np.std(days) / 7.0), 0.0, 1.0)) if len(days) > 1 else 0.5
    else:
        day_regularity = 0.0

    cv = float(np.std(amounts) / np.mean(amounts)) if np.mean(amounts) > 0 else 0.0

    return IncomeFeatures(
        months_observed=round(months_observed, 2),
        n_income_txns=len(credits),
        n_income_counterparties=len({e.counterparty_key for e in credits if e.counterparty_key}),
        has_monthly_salary_series=has_monthly_salary,
        salary_day_regularity=round(day_regularity, 3),
        income_amount_cv=round(cv, 3),
        zero_income_month_share=round(zero_share, 3),
        month_concentration=round(concentration, 3),
        harvest_month_share=round(harvest_amount / total, 3),
        agri_share=round(share(Category.AGRI_PROCEEDS), 3),
        gig_share=round(share(Category.GIG_PAYOUT), 3),
        business_share=round(share(Category.BUSINESS_RECEIPTS), 3),
        salary_share=round(share(Category.SALARY), 3),
        govt_benefit_share=round(share(Category.GOVT_BENEFIT), 3),
        credits_per_month=round(len(credits) / months_observed, 2),
        income_runs=float(income_runs),
        trailing_zero_months=float(trailing),
    )


def classify(
    enriched: list[EnrichedTransaction],
    series: list[RecurringSeries],
    *,
    override: IncomeType | None = None,
    model: object | None = None,
    as_of: date | None = None,
) -> IncomeTypeResult:
    """Classify the customer's income type.

    ``override`` is the mandatory correction path of report §5.1. It is honoured
    unconditionally and recorded as such: when a branch officer has looked at a
    customer and said "this is a sugarcane farmer", no amount of model
    confidence is permitted to overrule that.
    """
    features = extract_features(enriched, series, as_of=as_of)

    if override is not None:
        return IncomeTypeResult(
            income_type=override,
            confidence=1.0,
            method="override",
            evidence=("Income type set by human review; model output not used.",),
            features=features.as_dict(),
            overridden=True,
        )

    if features.n_income_txns == 0:
        return IncomeTypeResult(
            IncomeType.UNKNOWN, 0.0, "rules",
            ("No income credits detected in the consented window.",),
            features.as_dict(),
        )

    if model is not None:
        predicted = _model_predict(model, features)
        if predicted is not None:
            income_type, confidence = predicted
            return IncomeTypeResult(
                income_type, confidence, "model",
                (f"Supervised classifier over recurrence features (p={confidence:.2f}).",),
                features.as_dict(),
            )

    return _rule_classify(features)


def _rule_classify(f: IncomeFeatures) -> IncomeTypeResult:
    ev: list[str] = []

    # 1. Agricultural — checked before any irregularity verdict.
    if f.agri_share >= 0.35 or (f.harvest_month_share >= 0.70 and f.month_concentration >= 0.25):
        ev.append(f"Agricultural proceeds are {f.agri_share:.0%} of income.")
        ev.append(f"{f.harvest_month_share:.0%} of income arrives in harvest-marketing months.")
        ev.append("Long zero-income stretches are expected for this profile and are not stress.")
        return IncomeTypeResult(IncomeType.AGRICULTURAL, _conf(0.72, f), "rules", tuple(ev), f.as_dict())

    # 2. Seasonal — concentrated, repeating, and not merely a recent gap.
    #
    # The repetition test is what stops a job loss being read as a season. One
    # open gap at the end of the window is a customer who stopped earning; two
    # or more closed gaps is a customer who earns in bursts. Only the second is
    # seasonality, and only the second should relax the Twin's buffer.
    if f.zero_income_month_share >= 0.30 and f.month_concentration >= 0.12:
        repeating = f.income_runs >= 2
        gap_is_open = f.trailing_zero_months >= 2 and f.income_runs <= 1
        if repeating and not gap_is_open:
            ev.append(
                f"Income arrives in {int(f.income_runs)} distinct bursts with "
                f"{f.zero_income_month_share:.0%} of months carrying none."
            )
            ev.append(f"The income-less stretches repeat rather than running to the present day.")
            ev.append("Buffer requirements are widened accordingly; this is not treated as stress.")
            return IncomeTypeResult(IncomeType.SEASONAL, _conf(0.66, f), "rules", tuple(ev), f.as_dict())
        if gap_is_open:
            ev.append(
                f"Income stopped {int(f.trailing_zero_months)} months ago and has not resumed."
            )
            ev.append("This is an open gap, not a season — routed for stress assessment, not refusal.")

    # 3. Salaried — a real monthly series, not merely a salary-labelled credit.
    if f.has_monthly_salary_series and f.salary_share >= 0.45:
        if f.salary_day_regularity >= 0.6 and f.income_amount_cv <= 0.25:
            ev.append("Salary credit recurs monthly on a consistent date.")
            ev.append(f"Amount variation is low (CV {f.income_amount_cv:.2f}).")
            return IncomeTypeResult(
                IncomeType.SALARIED_STABLE, _conf(0.85, f), "rules", tuple(ev), f.as_dict()
            )
        ev.append("Salary credit recurs monthly but the date or amount moves.")
        ev.append(f"Date regularity {f.salary_day_regularity:.2f}, amount CV {f.income_amount_cv:.2f}.")
        ev.append("Treated as volatile for buffer sizing, not as a credit negative.")
        return IncomeTypeResult(
            IncomeType.SALARIED_VOLATILE, _conf(0.74, f), "rules", tuple(ev), f.as_dict()
        )

    # 4. Gig — many small credits, few counterparties (the platforms).
    if f.gig_share >= 0.35 or (f.credits_per_month >= 6 and f.n_income_counterparties <= 4):
        ev.append(f"{f.credits_per_month:.0f} income credits a month from {f.n_income_counterparties} sources.")
        ev.append(f"Platform payouts are {f.gig_share:.0%} of income.")
        return IncomeTypeResult(IncomeType.GIG, _conf(0.70, f), "rules", tuple(ev), f.as_dict())

    # 5. Business — many counterparties, irregular amounts.
    if f.business_share >= 0.35 or (f.n_income_counterparties >= 8 and f.income_amount_cv >= 0.5):
        ev.append(f"Receipts from {f.n_income_counterparties} distinct counterparties.")
        ev.append(f"Amount variation is high (CV {f.income_amount_cv:.2f}).")
        return IncomeTypeResult(IncomeType.BUSINESS, _conf(0.68, f), "rules", tuple(ev), f.as_dict())

    if f.salary_share >= 0.45:
        ev.append("Salary-labelled credits present without a stable monthly series.")
        return IncomeTypeResult(
            IncomeType.SALARIED_VOLATILE, _conf(0.55, f), "rules", tuple(ev), f.as_dict()
        )

    ev.append("No dominant income structure detected in the consented window.")
    ev.append("A human income-type correction is available and should be offered before any refusal.")
    return IncomeTypeResult(IncomeType.UNKNOWN, 0.30, "rules", tuple(ev), f.as_dict())


def _conf(base: float, f: IncomeFeatures) -> float:
    """Discount confidence when the observation window is short.

    Three months of history cannot establish an annual pattern, and a system
    that reports otherwise will deny a seasonal borrower on the strength of a
    window that never contained their season.
    """
    window_factor = min(f.months_observed / 9.0, 1.0)
    return round(float(np.clip(base * (0.55 + 0.45 * window_factor), 0.0, 0.99)), 3)


def _model_predict(model: object, f: IncomeFeatures) -> tuple[IncomeType, float] | None:
    try:
        import numpy as _np

        x = _np.array([[v for _, v in sorted(f.as_dict().items())]])
        proba = model.predict_proba(x)[0]                  # type: ignore[attr-defined]
        classes = list(model.classes_)                     # type: ignore[attr-defined]
    except Exception:
        return None
    idx = int(np.argmax(proba))
    try:
        return IncomeType(classes[idx]), float(proba[idx])
    except ValueError:
        return None


def _months_between(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def buffer_multiplier(income_type: IncomeType) -> float:
    """How many months of committed outflow this profile should hold in reserve.

    This is where the income label earns its keep. The same balance is comfort
    for a salaried customer and thin cover for a farmer between harvests, and
    the Twin's safe-buffer floor is scaled accordingly rather than set globally.
    """
    return {
        IncomeType.SALARIED_STABLE: 1.0,
        IncomeType.SALARIED_VOLATILE: 1.5,
        IncomeType.GIG: 2.0,
        IncomeType.BUSINESS: 2.0,
        IncomeType.SEASONAL: 3.0,
        IncomeType.AGRICULTURAL: 3.5,
        IncomeType.UNKNOWN: 2.0,
    }[income_type]
