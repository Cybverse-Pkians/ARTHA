"""The Suitability Gate.

Report §5.2 and §12. The Gate sits between the models and the customer and can
override the ranking entirely. Six checks, in order:

  1. hard eligibility rules
  2. affordability, against the Twin verdict and a minimum post-EMI buffer
  3. Recovery-Mode state — suppresses *all* selling if the customer is in stress
  4. the nudge budget — contacts per month and per-product cooldowns
  5. the empathy calendar — bereavement, job loss, examination season
  6. a fairness check on cohort benefit distribution

Two design decisions worth stating.

**Every check runs, even after one has failed.** The outcome is taken from the
first failure, but the trace records all six. A trace that stops at the first
failure cannot demonstrate that the remaining constraints were ever evaluated,
and report §6.7 promises the supervisor a gate trace, not a rejection note.

**The number of offers this Gate suppresses is a success metric.** It is
reported on the bank's own dashboard with a positive trend indicator (§2.2).
A recommendation engine whose dashboard celebrates the offers it did not make is
the point of the design, not a caveat to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..config import settings
from ..core import reason_codes as rc
from ..core.decision import GateCheck, ReasonEntry
from ..core.money import format_inr
from ..core.types import CustomerProfile, GateOutcome, ProductFamily, RecoveryState
from ..consent.manager import ConsentManager
from ..consent.purposes import Purpose
from ..engines.twin import Counterfactual, TwinResult, TwinVerdict
from ..products.catalogue import ProductOffer
from .conduct import EmpathyCalendar, NudgeBudget
from .fairness import FairnessMonitor
from .recovery import RecoveryMachine


@dataclass(frozen=True)
class GateDecision:
    outcome: GateOutcome
    trace: tuple[GateCheck, ...]
    reasons: tuple[ReasonEntry, ...]
    purposes_used: tuple[Purpose, ...] = field(default_factory=tuple)
    blocking_check: str | None = None

    @property
    def acts(self) -> bool:
        return self.outcome is GateOutcome.ACT


class SuitabilityGate:
    def __init__(
        self,
        *,
        recovery: RecoveryMachine,
        budget: NudgeBudget,
        calendar: EmpathyCalendar,
        fairness: FairnessMonitor,
        consent: ConsentManager,
    ) -> None:
        self.recovery = recovery
        self.budget = budget
        self.calendar = calendar
        self.fairness = fairness
        self.consent = consent

    def evaluate(
        self,
        profile: CustomerProfile,
        offer: ProductOffer | None,
        *,
        twin: TwinResult | None = None,
        counterfactual: Counterfactual | None = None,
        as_of: date | None = None,
        gender: str | None = None,
        is_assistance: bool = False,
    ) -> GateDecision:
        """Run the Gate.

        ``is_assistance`` marks an intervention offered as a service rather than
        a product sold — an EMI date shift for a customer in AT_RISK, say. It
        bypasses the conduct caps and the Recovery-Mode suppression, because
        those exist to stop *selling*, and refusing to offer help to a customer
        in difficulty because their nudge budget is exhausted would invert the
        purpose of the control.
        """
        as_of = as_of or date.today()
        trace: list[GateCheck] = []
        reasons: list[ReasonEntry] = []
        used: set[Purpose] = {Purpose.ACCOUNT_SERVICING}

        family = offer.product.family.value if offer else ProductFamily.LOAN.value

        # -- 0. consent ----------------------------------------------------
        needed = (
            Purpose.AFFORDABILITY_ASSESSMENT if is_assistance
            else Purpose.PRODUCT_RECOMMENDATION
        )
        consent_ok = self.consent.is_live(profile.customer_token, needed, as_of=as_of)
        trace.append(GateCheck(
            name="consent_purpose",
            passed=consent_ok,
            detail=(
                f"Purpose {needed.value} is live."
                if consent_ok else
                f"Purpose {needed.value} is not live; the engine did not run."
            ),
        ))
        if consent_ok:
            used.add(needed)

        # -- 1. hard eligibility -------------------------------------------
        if offer is not None:
            failing = offer.product.failing_rules(profile)
            trace.append(GateCheck(
                name="eligibility",
                passed=not failing,
                detail=(
                    "All hard eligibility rules satisfied."
                    if not failing else
                    "Failed: " + "; ".join(r.description for r in failing)
                ),
                reason_code=rc.ELG_HARD_RULE.code if failing else None,
            ))
            if failing:
                reasons.append(ReasonEntry(
                    rc.ELG_HARD_RULE.code, weight=1.0,
                    params={"rule": failing[0].description},
                ))
            if profile.thin_file:
                reasons.append(ReasonEntry(rc.ELG_THIN_FILE_ALT_DATA.code, weight=0.2))
        else:
            trace.append(GateCheck("eligibility", True, "No candidate product to evaluate."))

        # -- 2. affordability ----------------------------------------------
        trace.append(self._affordability_check(profile, offer, twin, reasons, as_of))
        if twin is not None:
            used.add(Purpose.AFFORDABILITY_ASSESSMENT)

        # -- 3. Recovery Mode ----------------------------------------------
        record = self.recovery.get(profile.customer_token)
        if is_assistance:
            recovery_ok, detail, code = True, (
                "Assistance is offered as a service; Recovery-Mode suppression does not apply."
            ), None
        elif record.suppresses_selling:
            recovery_ok, detail, code = False, (
                f"Customer is in {record.state.value}; all selling suppressed in every family."
            ), rc.REC_STRESS_SUPPRESSION.code
        elif record.state is RecoveryState.WATCH:
            recovery_ok, detail, code = False, (
                "Customer is in WATCH; new credit paused and no contact made."
            ), rc.REC_WATCH_PAUSE.code
        else:
            recovery_ok, detail, code = True, "Customer is STABLE.", None

        trace.append(GateCheck(
            "recovery_mode", recovery_ok, detail, code,
            outcome_if_failed=(
                GateOutcome.PROTECT if record.suppresses_selling else GateOutcome.SUPPRESS
            ),
        ))
        if code:
            reasons.append(ReasonEntry(code, weight=1.0))

        # -- 4. nudge budget -----------------------------------------------
        trace.extend(self._conduct_checks(profile, family, record, as_of, reasons, is_assistance))

        # -- 5. empathy calendar -------------------------------------------
        window = self.calendar.active(profile.customer_token, as_of)
        empathy_ok = is_assistance or window is None
        trace.append(GateCheck(
            "empathy_calendar", empathy_ok,
            ("No suppression window active." if empathy_ok else
             f"{window.event.value} window active until {window.end.isoformat()}. {window.evidence}"),
            rc.EMP_CALENDAR.code if not empathy_ok else None,
        ))
        if not empathy_ok:
            reasons.append(ReasonEntry(rc.EMP_CALENDAR.code, weight=0.9))

        # -- 6. fairness ----------------------------------------------------
        fair_ok, fair_detail = self.fairness.check(profile, gender=gender)
        trace.append(GateCheck(
            "fairness", fair_ok, fair_detail,
            rc.FAI_COHORT_DRIFT.code if not fair_ok else None,
            outcome_if_failed=GateOutcome.VERIFY,
        ))
        if not fair_ok:
            reasons.append(ReasonEntry(rc.FAI_COHORT_DRIFT.code, weight=0.8))

        outcome, blocking = self._resolve(trace, consent_ok)

        if outcome is GateOutcome.ACT and offer is not None:
            reasons.extend(self._favourable_reasons(offer, twin))

        return GateDecision(
            outcome=outcome,
            trace=tuple(trace),
            reasons=tuple(reasons),
            purposes_used=tuple(sorted(used, key=lambda p: p.value)),
            blocking_check=blocking,
        )

    # ------------------------------------------------------------------ parts

    def _affordability_check(
        self,
        profile: CustomerProfile,
        offer: ProductOffer | None,
        twin: TwinResult | None,
        reasons: list[ReasonEntry],
        as_of: date,
    ) -> GateCheck:
        if twin is None or offer is None:
            return GateCheck("affordability", True, "No obligation proposed; nothing to test.")

        # The obligation-to-income ceiling, applied alongside the simulation
        # rather than instead of it. The Twin can clear a customer whose ratio is
        # still outside policy, and policy wins.
        proposed_oti = (
            (profile.existing_emi_paise + offer.emi_paise) / profile.monthly_income_paise
            if profile.monthly_income_paise > 0 else 1.0
        )
        if proposed_oti > settings.obligation_to_income_ceiling:
            reasons.append(ReasonEntry(
                rc.AFF_OTI_CEILING.code, weight=1.0,
                params={"oti": f"{proposed_oti:.0%}"},
            ))
            return GateCheck(
                "affordability", False,
                (f"Obligation-to-income would reach {proposed_oti:.1%}, above the "
                 f"{settings.obligation_to_income_ceiling:.0%} ceiling."),
                rc.AFF_OTI_CEILING.code,
            )

        if twin.verdict is TwinVerdict.UNAFFORDABLE:
            month = twin.first_breach_date.strftime("%B") if twin.first_breach_date else "the horizon"
            reasons.append(ReasonEntry(
                rc.AFF_BUFFER_BREACH.code, weight=1.0, params={"month": month},
            ))
            return GateCheck(
                "affordability", False,
                (f"Twin projects a buffer breach with probability "
                 f"{twin.breach_probability:.1%} (ceiling {settings.breach_probability_ceiling:.0%}); "
                 f"safe buffer {format_inr(twin.safe_buffer_paise)}, "
                 f"lowest projected balance {format_inr(twin.min_balance_p05_paise)}."),
                rc.AFF_BUFFER_BREACH.code,
            )

        if twin.verdict is TwinVerdict.FRAGILE:
            failed = next((s for s in twin.scenarios if not s.passed), None)
            shock = failed.label.lower() if failed else "an unexpected expense"
            reasons.append(ReasonEntry(
                rc.AFF_SHOCK_FRAGILE.code, weight=1.0, params={"shock": shock},
            ))
            return GateCheck(
                "affordability", False,
                (f"Base case clears but the '{failed.label if failed else 'shock'}' scenario "
                 f"breaches the buffer at {failed.breach_probability:.1%} "
                 f"(ceiling {settings.breach_probability_ceiling:.0%})."),
                rc.AFF_SHOCK_FRAGILE.code,
            )

        reasons.append(ReasonEntry(rc.AFF_HEADROOM_OK.code, weight=0.6))
        return GateCheck(
            "affordability", True,
            (f"Twin clears base case and all {len(twin.scenarios)} shock scenarios. "
             f"Resilience {twin.resilience_score:.0f}/100; absorbs {twin.shocks_absorbed} "
             f"income shock(s)."),
        )

    def _conduct_checks(
        self,
        profile: CustomerProfile,
        family: str,
        record,
        as_of: date,
        reasons: list[ReasonEntry],
        is_assistance: bool,
    ) -> list[GateCheck]:
        token = profile.customer_token
        checks: list[GateCheck] = []

        if family in record.do_not_contact_families:
            checks.append(GateCheck(
                "do_not_ask_again", False,
                f"Customer asked not to be contacted about {family} again.",
                rc.NDG_DO_NOT_ASK.code,
            ))
            reasons.append(ReasonEntry(rc.NDG_DO_NOT_ASK.code, weight=1.0))
        else:
            checks.append(GateCheck("do_not_ask_again", True, "No standing suppression preference."))

        if is_assistance:
            checks.append(GateCheck(
                "nudge_budget", True,
                "Assistance is exempt from the contact cap; the cap governs selling.",
            ))
            checks.append(GateCheck("product_cooldown", True, "Not applicable to assistance."))
            return checks

        remaining = self.budget.remaining(token, as_of)
        checks.append(GateCheck(
            "nudge_budget", remaining > 0,
            (f"{remaining} of {self.budget.per_month} contacts remaining this month."
             if remaining > 0 else
             f"Monthly cap of {self.budget.per_month} contacts already used."),
            rc.NDG_BUDGET_EXHAUSTED.code if remaining <= 0 else None,
        ))
        if remaining <= 0:
            reasons.append(ReasonEntry(rc.NDG_BUDGET_EXHAUSTED.code, weight=0.7))

        cooling = self.budget.cooldown_active(token, family, as_of)
        days_left = self.budget.cooldown_remaining_days(token, family, as_of)
        checks.append(GateCheck(
            "product_cooldown", not cooling,
            (f"No cooldown active for {family}." if not cooling else
             f"{family} was offered recently; {days_left} days of cooldown remain."),
            rc.NDG_PRODUCT_COOLDOWN.code if cooling else None,
        ))
        if cooling:
            reasons.append(ReasonEntry(rc.NDG_PRODUCT_COOLDOWN.code, weight=0.7))

        return checks

    @staticmethod
    def _favourable_reasons(offer: ProductOffer, twin: TwinResult | None) -> list[ReasonEntry]:
        out: list[ReasonEntry] = []
        if offer.is_reduced_from_eligibility:
            out.append(ReasonEntry(
                rc.PRF_TWIN_SAFE_EXPOSURE.code, weight=0.95,
                params={
                    "eligible": format_inr(offer.eligible_amount_paise),
                    "recommended": format_inr(offer.amount_paise),
                },
            ))
        out.append(ReasonEntry(
            rc.PRF_DATE_ALIGNED.code, weight=0.5,
            params={"day": str(offer.day_of_month)},
        ))
        return out

    @staticmethod
    def _resolve(trace: list[GateCheck], consent_ok: bool) -> tuple[GateOutcome, str | None]:
        """The outcome is the first failure's verdict; silence is a valid one."""
        if not consent_ok:
            return GateOutcome.SUPPRESS, "consent_purpose"
        for check in trace:
            if not check.passed:
                return check.outcome_if_failed, check.name
        return GateOutcome.ACT, None
