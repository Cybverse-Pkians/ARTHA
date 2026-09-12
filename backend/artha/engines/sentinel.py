"""The Sentinel.

Report §6.3, §6.4 and Figure 7. The Sentinel separates three things that look
alike in transaction data and demand opposite responses:

* **fraud** — someone else is moving the customer's money, or the customer is
  being socially engineered into moving it themselves;
* **financial distress** — the customer is running out of room;
* **benign life change** — a relocation, a new baby, a festival, a season.

It then separates, within distress, **inability to pay from unwillingness to
pay**. Forbearance for genuine hardship is portfolio optimisation; forbearance
for strategic default is a giveaway.

Three properties the report insists on, implemented here rather than described:

1. Distress output is expressed as a **probability-of-default uplift over 90
   days**, in the bank's existing vocabulary, so existing risk systems can
   consume it directly rather than as an invented proprietary score.
2. Anomaly scoring is against the **customer's own baseline**, never a
   population average — population norms systematically misread rural, seasonal
   and agricultural profiles.
3. Alerts are thresholded at the **bank's actual daily contact capacity**. The
   operative question is not who is risky but which N customers should be
   contacted today, given N available slots.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from ..config import settings
from ..core import reason_codes as rc
from ..core.money import format_inr
from ..core.types import (
    DISCRETIONARY_CATEGORIES,
    Category,
    CustomerProfile,
    Direction,
    EnrichedTransaction,
    IncomeType,
    PayIntent,
    SentinelVerdict,
)
from ..ontology.recurrence import next_due_date


@dataclass(frozen=True)
class FraudSignal:
    """One matched row of Table 4."""

    pattern: str
    description: str
    response: str
    severity: float                     # 0..1
    evidence: tuple[str, ...] = field(default_factory=tuple)
    cooling_off_minutes: int = 0


@dataclass(frozen=True)
class SentinelResult:
    verdict: SentinelVerdict
    pd_uplift_90d: float                # percentage points, e.g. 0.042 == +4.2pp
    anomaly_score: float                # deviation from the customer's own baseline
    pay_intent: PayIntent
    lead_time_days: int | None          # days before the projected first missed payment
    evidence: tuple[str, ...] = field(default_factory=tuple)
    fraud_signals: tuple[FraudSignal, ...] = field(default_factory=tuple)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    contact_recommended: bool = False
    intervention_changes_outcome: bool = True

    @property
    def is_fraud(self) -> bool:
        return self.verdict is SentinelVerdict.FRAUD

    @property
    def is_distress(self) -> bool:
        return self.verdict is SentinelVerdict.FINANCIAL_DISTRESS


class Sentinel:
    def __init__(self, *, baseline_days: int = 180) -> None:
        self.baseline_days = baseline_days

    # ------------------------------------------------------------------ API

    def assess(
        self,
        profile: CustomerProfile,
        enriched: list[EnrichedTransaction],
        *,
        as_of: date | None = None,
        twin_resilience: float | None = None,
        missed_payment: bool = False,
    ) -> SentinelResult:
        as_of = as_of or date.today()

        fraud = self.detect_fraud(profile, enriched, as_of=as_of)
        if fraud:
            worst = max(fraud, key=lambda f: f.severity)
            return SentinelResult(
                verdict=SentinelVerdict.FRAUD,
                pd_uplift_90d=0.0,
                anomaly_score=worst.severity,
                pay_intent=PayIntent.INDETERMINATE,
                lead_time_days=None,
                evidence=(worst.description,),
                fraud_signals=tuple(fraud),
                reason_codes=(rc.SEN_FRAUD_HOLD.code,),
                contact_recommended=True,
            )

        anomaly, anomaly_evidence = self.baseline_deviation(profile, enriched, as_of)
        stress, stress_evidence, lead_time = self.distress_signals(
            profile, enriched, as_of, twin_resilience
        )

        intent, intent_evidence = self.ability_versus_willingness(
            profile, enriched, as_of, missed_payment=missed_payment
        )

        if intent is PayIntent.UNWILLING:
            return SentinelResult(
                verdict=SentinelVerdict.FINANCIAL_DISTRESS,
                pd_uplift_90d=round(stress * 0.4, 4),
                anomaly_score=round(anomaly, 3),
                pay_intent=intent,
                lead_time_days=lead_time,
                evidence=tuple(intent_evidence),
                reason_codes=(rc.SEN_UNWILLING.code,),
                contact_recommended=False,
                intervention_changes_outcome=False,
            )

        if stress >= 0.02:
            return SentinelResult(
                verdict=SentinelVerdict.FINANCIAL_DISTRESS,
                pd_uplift_90d=round(stress, 4),
                anomaly_score=round(anomaly, 3),
                pay_intent=intent,
                lead_time_days=lead_time,
                evidence=tuple(stress_evidence),
                reason_codes=(rc.SEN_STRESS_PREDICTED.code,),
                contact_recommended=True,
                intervention_changes_outcome=True,
            )

        if anomaly >= 2.5:
            return SentinelResult(
                verdict=SentinelVerdict.BENIGN_LIFE_CHANGE,
                pd_uplift_90d=0.0,
                anomaly_score=round(anomaly, 3),
                pay_intent=PayIntent.INDETERMINATE,
                lead_time_days=None,
                evidence=tuple(anomaly_evidence),
                reason_codes=(rc.SEN_BENIGN_CHANGE.code,),
                contact_recommended=False,
            )

        return SentinelResult(
            verdict=SentinelVerdict.NORMAL,
            pd_uplift_90d=0.0,
            anomaly_score=round(anomaly, 3),
            pay_intent=PayIntent.INDETERMINATE,
            lead_time_days=None,
            evidence=("No material deviation from this customer's own baseline.",),
        )

    # ------------------------------------------------------------- fraud

    def detect_fraud(
        self, profile: CustomerProfile, enriched: list[EnrichedTransaction], *, as_of: date
    ) -> list[FraudSignal]:
        """Table 4, implemented. Patterns, signals, responses."""
        signals: list[FraudSignal] = []
        recent = [e for e in enriched if e.value_date >= as_of - timedelta(days=3)]
        debits = [e for e in recent if e.direction is Direction.DEBIT]
        if not debits:
            return signals

        known = {
            e.counterparty_key for e in enriched
            if e.value_date < as_of - timedelta(days=30) and e.counterparty_key
        }
        new_payees = [e for e in debits if e.counterparty_key and e.counterparty_key not in known]

        # First-time large payee — any first transfer above a threshold.
        large_new = [e for e in new_payees if abs(e.amount_paise) >= 20_000 * 100]
        if large_new:
            signals.append(FraudSignal(
                pattern="first_time_large_payee",
                description=(
                    f"First transfer of {format_inr(abs(large_new[0].amount_paise))} to a "
                    f"beneficiary not seen in the last 30 days."
                ),
                response="Delay window with a cancel option",
                severity=0.55,
                evidence=tuple(e.txn.txn_id for e in large_new[:3]),
                cooling_off_minutes=30,
            ))

        # Account takeover — new payee plus near-limit transfer in one session.
        session_total = sum(abs(e.amount_paise) for e in new_payees)
        if len(new_payees) >= 2 and session_total >= profile.balance_paise * 0.5 > 0:
            signals.append(FraudSignal(
                pattern="account_takeover",
                description=(
                    f"{len(new_payees)} new beneficiaries and {format_inr(session_total)} "
                    f"moved in a single session — {session_total / max(profile.balance_paise, 1):.0%} "
                    f"of the balance."
                ),
                response="Cooling-off hold and step-up authentication",
                severity=0.92,
                evidence=tuple(e.txn.txn_id for e in new_payees[:4]),
                cooling_off_minutes=60,
            ))

        # Mule behaviour — rapid fan-in then fan-out, pass-through balances.
        #
        # Scored against the customer's *own* baseline, not a population shape.
        # A kirana owner's account legitimately shows heavy fan-in and fan-out
        # with near-total pass-through every week of the year; that is their
        # business, not laundering. Report §7.4 makes per-customer baselines the
        # rule precisely because population norms misread these profiles, and a
        # naive version of this check would flag every small trader in the book.
        window = [e for e in enriched if e.value_date >= as_of - timedelta(days=7)]
        credits_in = [e for e in window if e.direction is Direction.CREDIT]
        debits_out = [e for e in window if e.direction is Direction.DEBIT]

        prior = [
            e for e in enriched
            if as_of - timedelta(days=63) <= e.value_date < as_of - timedelta(days=7)
        ]
        weekly_baseline = len(prior) / 8.0 if prior else 0.0
        surge = (
            len(window) > weekly_baseline * 1.8 if weekly_baseline > 0 else True
        )
        fan_in_out_is_normal_here = profile.income_type in {
            IncomeType.BUSINESS, IncomeType.GIG
        }

        if (
            len(credits_in) >= 5
            and len(debits_out) >= 5
            and surge
            and not fan_in_out_is_normal_here
        ):
            in_total = sum(abs(e.amount_paise) for e in credits_in)
            out_total = sum(abs(e.amount_paise) for e in debits_out)
            if in_total > 0 and 0.85 <= out_total / in_total <= 1.15:
                signals.append(FraudSignal(
                    pattern="mule_behaviour",
                    description=(
                        f"{len(credits_in)} inflows and {len(debits_out)} outflows in 7 days "
                        f"with {out_total / in_total:.0%} pass-through, against an own "
                        f"baseline of {weekly_baseline:.0f} transactions a week."
                    ),
                    response="Hold, review queue and reporting path",
                    severity=0.80,
                    evidence=tuple(e.txn.txn_id for e in debits_out[:4]),
                    cooling_off_minutes=0,
                ))

        # Elder targeting — age, unusual pattern, new beneficiary.
        if profile.age and profile.age >= 60 and new_payees:
            signals.append(FraudSignal(
                pattern="elder_targeting",
                description=(
                    f"Customer is {profile.age} and is transferring to a new beneficiary "
                    f"in an unusual pattern."
                ),
                response="Opt-in trusted-contact notification",
                severity=0.70,
                evidence=tuple(e.txn.txn_id for e in new_payees[:3]),
                cooling_off_minutes=30,
            ))

        return signals

    # --------------------------------------------------------- own baseline

    def baseline_deviation(
        self, profile: CustomerProfile, enriched: list[EnrichedTransaction], as_of: date
    ) -> tuple[float, list[str]]:
        """Score the last 30 days against this customer's own prior behaviour.

        A z-score against the customer's own history, not the population's. A
        farmer spending nothing for three months is not an outlier against
        themselves, and a population model is the reason rural profiles get
        flagged constantly by systems that do this the easy way.
        """
        cutoff = as_of - timedelta(days=30)
        baseline_start = as_of - timedelta(days=self.baseline_days)

        baseline = [
            e for e in enriched
            if baseline_start <= e.value_date < cutoff and e.direction is Direction.DEBIT
        ]
        recent = [
            e for e in enriched if e.value_date >= cutoff and e.direction is Direction.DEBIT
        ]
        if len(baseline) < 20 or not recent:
            return 0.0, ["Insufficient own-history to establish a baseline."]

        by_month: dict[tuple[int, int], float] = defaultdict(float)
        for e in baseline:
            by_month[(e.value_date.year, e.value_date.month)] += abs(e.amount_paise)
        monthly = np.array(list(by_month.values()), dtype=float)
        if monthly.size < 2:
            return 0.0, ["Insufficient own-history to establish a baseline."]

        recent_total = float(sum(abs(e.amount_paise) for e in recent))
        mu, sigma = float(monthly.mean()), float(monthly.std())
        z = abs(recent_total - mu) / sigma if sigma > 0 else 0.0

        evidence = [
            f"Last 30 days of outflow: {format_inr(int(recent_total))}.",
            f"Own baseline: {format_inr(int(mu))} a month over "
            f"{monthly.size} months (sd {format_inr(int(sigma))}).",
            f"Deviation {z:.1f} standard deviations from this customer's own norm.",
        ]
        return float(z), evidence

    # ------------------------------------------------------------ distress

    def distress_signals(
        self,
        profile: CustomerProfile,
        enriched: list[EnrichedTransaction],
        as_of: date,
        twin_resilience: float | None,
    ) -> tuple[float, list[str], int | None]:
        """Estimate a 90-day PD uplift, with lead time to the first missed payment.

        Lead time is the headline metric of report §5.3: model quality is
        reported as *days of lead time before the first missed payment* rather
        than as accuracy, because days convert into rungs on the Intervention
        Ladder and rungs convert into rupees.
        """
        uplift = 0.0
        evidence: list[str] = []
        lead_time: int | None = None

        # 1. The EMI falls before income arrives — the single most actionable signal.
        emi_series = [
            s for s in profile.series
            if s.direction is Direction.DEBIT and s.category is Category.EMI and s.day_of_month
        ]
        income_day = None
        income_candidates = [
            s for s in profile.series
            if s.direction is Direction.CREDIT and s.day_of_month
            and s.category in {Category.SALARY, Category.GIG_PAYOUT}
        ]
        if income_candidates:
            income_day = max(income_candidates, key=lambda s: s.median_amount_paise).day_of_month

        if emi_series and income_day:
            emi = emi_series[0]
            gap = (income_day - emi.day_of_month) % 30
            if 0 < gap <= 12:
                uplift += 0.035
                evidence.append(
                    f"EMI falls on the {emi.day_of_month}, {gap} days before income "
                    f"typically arrives on the {income_day}."
                )
                due = next_due_date(emi, as_of)
                if due:
                    lead_time = max((due - as_of).days, 0)

        # 2. Balance trending toward the buffer.
        if profile.monthly_committed_outflow_paise > 0:
            cover = profile.balance_paise / profile.monthly_committed_outflow_paise
            if cover < 0.75:
                uplift += 0.045
                evidence.append(
                    f"Balance covers only {cover:.1f} months of committed outflow."
                )
            elif cover < 1.25:
                uplift += 0.018
                evidence.append(f"Balance cover has fallen to {cover:.1f} months.")

        # 3. Obligation-to-income.
        if profile.obligation_to_income > 0.40:
            uplift += 0.030
            evidence.append(
                f"Existing EMIs take {profile.obligation_to_income:.0%} of assessed income."
            )

        # 4. High-cost borrowing appearing — borrowing to service borrowing.
        recent_high_cost = [
            e for e in enriched
            if e.value_date >= as_of - timedelta(days=60)
            and (e.category is Category.HIGH_COST_CREDIT
                 or (e.merchant and e.merchant.is_high_cost_lender))
        ]
        if recent_high_cost:
            uplift += 0.040
            evidence.append(
                f"{len(recent_high_cost)} payments to app lenders in 60 days."
            )

        # 5. The Twin's own verdict, where one was run.
        if twin_resilience is not None and twin_resilience < 40:
            uplift += 0.035
            evidence.append(f"Twin resilience is {twin_resilience:.0f}/100.")

        # Seasonal and agricultural profiles are not penalised for a quiet month.
        if profile.income_type in {IncomeType.AGRICULTURAL, IncomeType.SEASONAL}:
            uplift *= 0.55
            evidence.append(
                "Uplift discounted: income-less months are normal for this profile."
            )

        return float(min(uplift, 0.60)), evidence, lead_time

    # ------------------------------------------- ability versus willingness

    def ability_versus_willingness(
        self,
        profile: CustomerProfile,
        enriched: list[EnrichedTransaction],
        as_of: date,
        *,
        missed_payment: bool,
    ) -> tuple[PayIntent, list[str]]:
        """Distinguish cannot-pay from will-not-pay (report §6.3).

        A strategic defaulter often shows a healthy balance and continued
        discretionary spending while missing the EMI. The two have opposite
        correct responses, so conflating them is not a rounding error — it is
        either a giveaway to someone gaming the bank, or collections pressure on
        someone in genuine hardship.
        """
        if not missed_payment:
            return PayIntent.INDETERMINATE, []

        recent = [e for e in enriched if e.value_date >= as_of - timedelta(days=30)]

        # Gambling is counted as non-essential spend here, not excluded as its
        # own category. Someone funding a gaming platform in the same month they
        # missed an instalment is making a choice about where the money goes,
        # which is exactly the question this method exists to answer.
        non_essential = DISCRETIONARY_CATEGORIES | {Category.GAMBLING}
        discretionary = sum(
            abs(e.amount_paise) for e in recent
            if e.direction is Direction.DEBIT and e.category in non_essential
        )
        gambling = sum(
            abs(e.amount_paise) for e in recent
            if e.direction is Direction.DEBIT and e.category is Category.GAMBLING
        )
        emi_due = profile.existing_emi_paise

        # The balance test is the discriminator: holding more than twice the
        # instalment on the day it was missed means the money was there. The
        # spending test corroborates it, and is deliberately not set at parity
        # with the EMI — a household in genuine hardship still buys some things,
        # and requiring them to have spent an entire EMI on non-essentials before
        # believing them would be the wrong way round.
        healthy_balance = profile.balance_paise > emi_due * 2
        sustained_spend = discretionary >= emi_due * 0.4 or gambling > 0

        evidence: list[str] = []
        if healthy_balance and sustained_spend:
            evidence.append(
                f"Balance is {format_inr(profile.balance_paise)} against an EMI of "
                f"{format_inr(emi_due)}."
            )
            evidence.append(
                f"Discretionary spending of {format_inr(discretionary)} continued in "
                f"the same period as the missed payment."
            )
            if gambling > 0:
                evidence.append(f"Including {format_inr(gambling)} on gaming platforms.")
            evidence.append(
                "Capacity to pay appears intact; forbearance is withheld and the "
                "account routes to standard recovery."
            )
            return PayIntent.UNWILLING, evidence

        evidence.append(
            f"Balance {format_inr(profile.balance_paise)} is insufficient against an EMI "
            f"of {format_inr(emi_due)}; discretionary spending has not been maintained."
        )
        return PayIntent.UNABLE, evidence


# ------------------------------------------------- portfolio-level detection


@dataclass(frozen=True)
class CorrelatedAlert:
    """Report §6.3: 340 flagged customers sharing one employer is not 340 events.

    Grouping salary-credit timing by employer surfaces a payroll delay before
    any individual customer misses a payment. The computation is inexpensive and
    the signal is invisible to any model that reasons about one customer at a
    time — which is what makes it worth doing at all.
    """

    dimension: str                       # employer | sector | district
    key: str
    affected_customers: int
    median_delay_days: float
    description: str
    customer_tokens: tuple[str, ...] = field(default_factory=tuple)


def detect_correlated_stress(
    observations: list[tuple[str, str, int]],
    *,
    dimension: str = "employer",
    min_cluster: int | None = None,
    min_delay_days: float = 3.0,
) -> list[CorrelatedAlert]:
    """Find clusters of customers whose income is late together.

    ``observations`` is a list of (customer_token, group_key, delay_days).
    """
    min_cluster = min_cluster or settings.correlated_alert_min_cluster
    grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for token, key, delay in observations:
        if key:
            grouped[key].append((token, delay))

    alerts: list[CorrelatedAlert] = []
    for key, members in grouped.items():
        delayed = [(t, d) for t, d in members if d >= min_delay_days]
        if len(delayed) < min_cluster:
            continue
        median_delay = float(np.median([d for _, d in delayed]))
        alerts.append(CorrelatedAlert(
            dimension=dimension,
            key=key,
            affected_customers=len(delayed),
            median_delay_days=round(median_delay, 1),
            description=(
                f"{len(delayed)} customers sharing {dimension} '{key}' show salary "
                f"credits a median {median_delay:.0f} days late. This is one payroll "
                f"event, not {len(delayed)} independent borrower events."
            ),
            customer_tokens=tuple(t for t, _ in delayed),
        ))

    alerts.sort(key=lambda a: -a.affected_customers)
    return alerts


def rank_for_capacity(
    results: list[tuple[str, SentinelResult]],
    *,
    capacity: int | None = None,
) -> list[tuple[str, SentinelResult]]:
    """Choose which N customers to contact today.

    Report §6.3: a bank has finite calling capacity, so the operative question is
    not who is risky but which N should be contacted, given N slots. Customers
    for whom contact would not change the outcome are excluded before ranking
    rather than ranked and then ignored — relationship-manager time is the scarce
    resource being allocated, and spending it on a certainty is spending it badly.
    """
    capacity = capacity or settings.daily_contact_capacity
    actionable = [
        (token, r) for token, r in results
        if r.contact_recommended and r.intervention_changes_outcome
    ]
    actionable.sort(
        key=lambda pair: (
            -pair[1].pd_uplift_90d,
            pair[1].lead_time_days if pair[1].lead_time_days is not None else 999,
        )
    )
    return actionable[:capacity]


DEFAULT_SENTINEL = Sentinel()
