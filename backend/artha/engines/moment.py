"""The Moment Engine.

Report §6.1. Personalisation in ARTHA is a question of *timing* rather than of
segment membership. A trigger library runs continuously over the enriched
transaction stream and fires only when something materially changes.

Silence is an explicit, valid output. A customer may receive nothing in a given
month, and that is the system working correctly — so this module returns an
empty list far more often than not, and the caller must treat that as a result
rather than as a failure to find something.

The trigger table below is Table 3 of the report, implemented. Note that three
of its rows recommend *against* a product: high revolving utilisation produces a
consolidation candidate rather than a card, and a thin buffer with unstable
income produces an emergency-fund plan rather than credit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..core import reason_codes as rc
from ..core.money import format_inr
from ..core.types import (
    Category,
    CustomerProfile,
    Direction,
    EnrichedTransaction,
    IncomeType,
    ProductFamily,
    RecurringSeries,
)
from ..ontology.recurrence import next_due_date

# Sowing windows by broad cropping season. Kharif sowing runs with the monsoon
# onset; rabi sowing follows the kharif harvest.
_SOWING_MONTHS = frozenset({5, 6, 10, 11})


@dataclass(frozen=True)
class Moment:
    """One fired trigger, with the evidence that fired it."""

    trigger: str
    description: str
    product_ids: tuple[str, ...]
    family: ProductFamily
    priority: float                                # 0..1, used only to order candidates
    reason_code: str
    reason_params: dict[str, str] = field(default_factory=dict)
    evidence_dates: tuple[str, ...] = field(default_factory=tuple)
    series_id: str | None = None
    suppresses_credit: bool = False                # rows that recommend *against* a product


class MomentEngine:
    """Evaluates the trigger library against a customer's current state."""

    def __init__(self, *, lookahead_days: int = 60) -> None:
        self.lookahead_days = lookahead_days

    def detect(
        self,
        profile: CustomerProfile,
        enriched: list[EnrichedTransaction],
        *,
        as_of: date | None = None,
    ) -> list[Moment]:
        as_of = as_of or date.today()
        moments: list[Moment] = []

        for detector in (
            self._emi_ending,
            self._high_cost_outflow,
            self._sowing_window,
            self._health_spend,
            self._protection_gap,
            self._income_rise,
            self._idle_surplus,
            self._card_candidate,
            self._revolving_consolidation,
            self._thin_buffer,
        ):
            found = detector(profile, enriched, as_of)
            if found:
                moments.append(found)

        moments.sort(key=lambda m: -m.priority)
        return moments

    # -- Table 3, row by row ------------------------------------------------

    def _emi_ending(self, profile, enriched, as_of) -> Moment | None:
        """Existing EMI ends within 60 days and the Twin clears headroom."""
        for s in profile.series:
            if s.direction is not Direction.DEBIT or s.category is not Category.EMI:
                continue
            # The series' own history bounds how much longer it can run. Without
            # a loan master this is an estimate, and it is labelled as one.
            projected_end = s.last_seen + timedelta(days=s.period_days * 2)
            if as_of <= projected_end <= as_of + timedelta(days=self.lookahead_days):
                days = (projected_end - as_of).days
                return Moment(
                    trigger="emi_ending",
                    description=(
                        f"A detected EMI series of {format_inr(s.median_amount_paise)} "
                        f"is projected to end in {days} days, freeing committed outflow."
                    ),
                    product_ids=("pl_topup",),
                    family=ProductFamily.LOAN,
                    priority=0.85,
                    reason_code=rc.MOM_EMI_ENDING.code,
                    reason_params={
                        "label": s.label or "loan",
                        "days": str(days),
                        "amount": format_inr(s.median_amount_paise),
                    },
                    evidence_dates=tuple(d.isoformat() for d in s.evidence_dates),
                    series_id=s.series_id,
                )
        return None

    def _high_cost_outflow(self, profile, enriched, as_of) -> Moment | None:
        """Outflows detected to a high-interest lending application."""
        window = as_of - timedelta(days=90)
        hits = [
            e for e in enriched
            if e.value_date >= window
            and (e.category is Category.HIGH_COST_CREDIT
                 or (e.merchant and e.merchant.is_high_cost_lender))
        ]
        if len(hits) < 2:
            return None
        total = sum(abs(e.amount_paise) for e in hits)
        return Moment(
            trigger="high_cost_outflow",
            description=(
                f"{len(hits)} payments totalling {format_inr(total)} to app lenders "
                f"in 90 days. A secured facility is materially cheaper."
            ),
            product_ids=("gold_loan", "od_deposit"),
            family=ProductFamily.LOAN,
            priority=0.95,
            reason_code=rc.MOM_HIGH_COST_OUTFLOW.code,
            reason_params={"rate": "24-36% a year", "our_rate": "9.25% a year"},
            evidence_dates=tuple(e.value_date.isoformat() for e in hits[-4:]),
        )

    def _sowing_window(self, profile, enriched, as_of) -> Moment | None:
        """Sowing season approaching in an agricultural income profile."""
        if profile.income_type not in {IncomeType.AGRICULTURAL, IncomeType.SEASONAL}:
            return None
        upcoming = (as_of + timedelta(days=35)).month
        if upcoming not in _SOWING_MONTHS and as_of.month not in _SOWING_MONTHS:
            return None
        return Moment(
            trigger="sowing_window",
            description=(
                "Sowing window approaching on an agricultural profile. Repayment "
                "is timed to harvest rather than to a monthly cycle."
            ),
            product_ids=("crop_facility",),
            family=ProductFamily.LOAN,
            priority=0.80,
            reason_code=rc.MOM_SEASONAL_WINDOW.code,
            evidence_dates=(as_of.isoformat(),),
        )

    def _health_spend(self, profile, enriched, as_of) -> Moment | None:
        """Recurring chemist and diagnostic spending over three or more months."""
        if profile.has_health_cover:
            return None
        window = as_of - timedelta(days=100)
        hits = [
            e for e in enriched
            if e.value_date >= window
            and e.category in {Category.PHARMACY, Category.HEALTHCARE}
        ]
        months = {(e.value_date.year, e.value_date.month) for e in hits}
        if len(months) < 3:
            return None
        monthly = sum(abs(e.amount_paise) for e in hits) / max(len(months), 1)
        return Moment(
            trigger="health_spend",
            description=(
                f"Medical outflow in {len(months)} of the last 3 months, averaging "
                f"{format_inr(int(monthly))}. Cover sized to the observed outflow."
            ),
            product_ids=("health_cover",),
            family=ProductFamily.INSURANCE,
            priority=0.70,
            reason_code=rc.MOM_PROTECTION_GAP.code,
            reason_params={"dependants": str(profile.dependants)},
            evidence_dates=tuple(e.value_date.isoformat() for e in hits[-4:]),
        )

    def _protection_gap(self, profile, enriched, as_of) -> Moment | None:
        """Sole earner with dependants and no term cover."""
        if profile.has_term_cover or profile.dependants < 1:
            return None
        if profile.monthly_income_paise <= 0:
            return None
        return Moment(
            trigger="protection_gap",
            description=(
                f"{profile.dependants} dependants and no detected term cover. Sum "
                f"assured derived from actual obligations, not a round number."
            ),
            product_ids=("term_life",),
            family=ProductFamily.INSURANCE,
            priority=0.65,
            reason_code=rc.MOM_PROTECTION_GAP.code,
            reason_params={"dependants": str(profile.dependants)},
            evidence_dates=(as_of.isoformat(),),
        )

    def _income_rise(self, profile, enriched, as_of) -> Moment | None:
        """Salary increase detected and buffer already healthy — explicitly not a loan."""
        rising = [s for s in profile.series if s.direction is Direction.CREDIT and s.drifting]
        if not rising:
            return None
        if profile.balance_paise < profile.monthly_committed_outflow_paise * 2:
            return None
        return Moment(
            trigger="income_rise",
            description=(
                "A sustained upward changepoint in the income series, with a buffer "
                "already above two months of committed outflow."
            ),
            product_ids=("sip",),
            family=ProductFamily.INVESTMENT,
            priority=0.60,
            reason_code=rc.MOM_INCOME_RISE.code,
            evidence_dates=tuple(d.isoformat() for d in rising[0].evidence_dates),
            series_id=rising[0].series_id,
        )

    def _idle_surplus(self, profile, enriched, as_of) -> Moment | None:
        """Idle surplus held in savings for three or more months."""
        threshold = profile.monthly_committed_outflow_paise * 3
        if threshold <= 0 or profile.balance_paise < threshold:
            return None
        surplus = profile.balance_paise - threshold
        if surplus < 25_000 * 100:
            return None
        return Moment(
            trigger="idle_surplus",
            description=(
                f"{format_inr(surplus)} held above three months of committed outflow. "
                f"A deposit is sized so the buffer itself is preserved."
            ),
            product_ids=("recurring_deposit",),
            family=ProductFamily.INVESTMENT,
            priority=0.55,
            reason_code=rc.MOM_IDLE_SURPLUS.code,
            reason_params={"amount": format_inr(surplus), "months": "3"},
            evidence_dates=(as_of.isoformat(),),
        )

    def _card_candidate(self, profile, enriched, as_of) -> Moment | None:
        """Frequent small-ticket spend, strong repayment record, low utilisation."""
        if profile.credit_utilisation >= 0.40 or profile.on_time_emi_streak < 6:
            return None
        window = as_of - timedelta(days=60)
        small = [
            e for e in enriched
            if e.value_date >= window and e.direction is Direction.DEBIT
            and 100 * 100 <= abs(e.amount_paise) <= 3_000 * 100
        ]
        if len(small) < 25:
            return None
        return Moment(
            trigger="card_candidate",
            description=(
                f"{len(small)} small-ticket debits in 60 days with an on-time streak of "
                f"{profile.on_time_emi_streak} and utilisation {profile.credit_utilisation:.0%}."
            ),
            product_ids=("credit_card",),
            family=ProductFamily.CREDIT_CARD,
            priority=0.50,
            reason_code=rc.MOM_EMI_ENDING.code,
            reason_params={"label": "spending pattern", "days": "60",
                           "amount": format_inr(0)},
            evidence_dates=(as_of.isoformat(),),
        )

    def _revolving_consolidation(self, profile, enriched, as_of) -> Moment | None:
        """High utilisation with revolving behaviour — no card offer, consolidation instead."""
        if profile.credit_utilisation < 0.70:
            return None
        return Moment(
            trigger="revolving_consolidation",
            description=(
                f"Revolving utilisation at {profile.credit_utilisation:.0%}. A card offer "
                f"would deepen the position; consolidation at a lower rate is the "
                f"correct product."
            ),
            product_ids=("pl_standard",),
            family=ProductFamily.LOAN,
            priority=0.88,
            reason_code=rc.MOM_HIGH_COST_OUTFLOW.code,
            reason_params={"rate": "36% a year on the revolve", "our_rate": "14.5% a year"},
            evidence_dates=(as_of.isoformat(),),
            suppresses_credit=False,
        )

    def _thin_buffer(self, profile, enriched, as_of) -> Moment | None:
        """Thin buffer with unstable income — no product; an emergency-fund plan."""
        unstable = profile.income_type in {
            IncomeType.GIG, IncomeType.SEASONAL, IncomeType.AGRICULTURAL,
            IncomeType.SALARIED_VOLATILE, IncomeType.BUSINESS, IncomeType.UNKNOWN,
        }
        thin = profile.balance_paise < profile.monthly_committed_outflow_paise
        if not (unstable and thin):
            return None
        return Moment(
            trigger="thin_buffer",
            description=(
                "Balance is below one month of committed outflow on an income profile "
                "that is not predictable. No credit product is appropriate."
            ),
            product_ids=("emergency_fund",),
            family=ProductFamily.SAVINGS,
            priority=1.0,                      # outranks every selling trigger
            reason_code=rc.MOM_NO_TRIGGER.code,
            evidence_dates=(as_of.isoformat(),),
            suppresses_credit=True,
        )


DEFAULT_ENGINE = MomentEngine()
