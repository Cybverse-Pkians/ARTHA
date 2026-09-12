"""The Intervention Ladder.

Report §5.3 and Figure 4, and one of the five novelty claims in §12.

The error this module exists to correct: **restructuring is not free for a
bank.** Under RBI's framework for the resolution of stressed assets,
restructuring granted on account of borrower financial difficulty generally
carries asset-classification and provisioning consequences. A system that simply
restructures stressed loans hands the bank a cost and calls it empathy.

The resolution is that interventions are not equal, and the early ones are
cheaper in *regulatory* terms, not merely in economic ones. ARTHA therefore
leads with shifting the EMI date to follow the customer's actual income:
genuine cash-flow relief, ordinarily treated as a servicing change rather than
a concession granted for financial difficulty, and therefore real relief at
effectively no regulatory cost.

This reframes what the machine learning is for. Its function is to **buy time**,
because each week of earlier detection moves the customer one rung down a ladder
whose rungs differ by orders of magnitude.

REGULATORY STATUS: the treatment described for each rung is a design hypothesis
stated as such in report §11.2, to be verified against the current RBI circulars
before submission. It is not legal advice and the ``verify_against_circular``
flag on each rung says so in the data itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import IntEnum

from ..core import reason_codes as rc
from ..core.money import emi_paise, format_inr, total_cost_paise
from ..core.types import CustomerProfile, IncomeType, PayIntent
from ..features.builder import income_arrival_day


#: Splitting an instalment helps only where income arrives more than once a
#: month. Offering it to a salaried customer with a single monthly credit
#: would add a debit without adding relief.
_SPLIT_SUITED_INCOME = frozenset({
    IncomeType.GIG,
    IncomeType.SEASONAL,
    IncomeType.AGRICULTURAL,
    IncomeType.BUSINESS,
})


class Rung(IntEnum):
    """Ordered by cost. Lower is cheaper and is always tried first."""

    EMI_DATE_SHIFT = 1
    PARTIAL_PREPAYMENT_PLAN = 2
    SHORT_PAYMENT_HOLIDAY = 3
    TENURE_EXTENSION = 4
    FORMAL_RESTRUCTURE = 5
    COLLECTIONS = 6            # not an intervention — the absence of one


class RegCost(IntEnum):
    """The *supervisory* cost of an intervention, as a value the code can read.

    This was previously only the English prose in ``Intervention.regulatory_cost``,
    which every caller rendered and none branched on — so the two-tier escalation
    the design claims was a caption rather than a control. Typing it lets the
    Gate refuse to auto-propose a rung that would cost the bank an asset
    downgrade, and route it to a human credit officer instead.

    The prose is retained alongside as ``regulatory_cost``; it says *why*, and
    this says *what to do about it*.
    """

    NONE = 0                   # servicing change — ARTHA may propose freely
    POSSIBLE_CONCESSION = 1    # may be a concession; assess case by case
    DOWNGRADE_EXPECTED = 2     # escalate to a human credit officer

    @property
    def requires_human_credit_officer(self) -> bool:
        return self is RegCost.DOWNGRADE_EXPECTED

    @property
    def auto_proposable(self) -> bool:
        """Whether ARTHA may put this in front of a customer on its own."""
        return self is RegCost.NONE


@dataclass(frozen=True)
class Intervention:
    rung: Rung
    name: str
    description: str
    customer_sentence: str
    regulatory_cost: str
    reg_cost: RegCost
    economic_cost_paise: int
    reason_code: str
    reason_params: dict[str, str] = field(default_factory=dict)
    reversible: bool = True
    requires_customer_consent: bool = True
    verify_against_circular: bool = True
    new_emi_paise: int | None = None
    new_day_of_month: int | None = None
    new_tenure_months: int | None = None
    additional_total_cost_paise: int = 0


@dataclass(frozen=True)
class LadderResult:
    recommended: Intervention | None
    alternatives: tuple[Intervention, ...] = field(default_factory=tuple)
    withheld_reason: str = ""

    @property
    def has_recommendation(self) -> bool:
        return self.recommended is not None


class InterventionLadder:
    def build(
        self,
        profile: CustomerProfile,
        *,
        current_emi_paise: int,
        current_day_of_month: int,
        remaining_tenure_months: int,
        annual_rate: float,
        outstanding_paise: int,
        pay_intent: PayIntent = PayIntent.UNABLE,
        lead_time_days: int | None = None,
        as_of: date | None = None,
    ) -> LadderResult:
        """Build the ladder and recommend the cheapest rung still available.

        ``lead_time_days`` is what converts model quality into money, and is
        why report §5.3 reports lead time rather than accuracy: days convert
        into rungs and rungs differ by orders of magnitude. Passing it applies
        ``lead_time_to_rung`` as a *floor* — a customer found three days before
        a due date cannot be helped by moving that date, so the cheap rungs are
        withdrawn rather than recommended and left to fail.

        Omitting it means "lead time unknown", and the ladder is not
        constrained. That is deliberately not the same as no time being left:
        an unknown must not silently escalate every customer to a restructure.

        Forbearance is withheld outright where the Sentinel has determined
        unwillingness rather than inability. Report §6.3: forbearance for genuine
        hardship is portfolio optimisation; forbearance for strategic default is
        a giveaway, and the system should not be capable of handing one out by
        omission.
        """
        as_of = as_of or date.today()

        if pay_intent is PayIntent.UNWILLING:
            return LadderResult(
                recommended=None,
                withheld_reason=(
                    "Capacity to pay appears intact. Forbearance is withheld and the "
                    "account follows the standard recovery path; the evidence is "
                    "attached to the case for human review."
                ),
            )

        rungs: list[Intervention] = []

        shift = self._emi_date_shift(profile, current_emi_paise, current_day_of_month)
        if shift:
            rungs.append(shift)

        split = self._split_instalment(profile, current_emi_paise, current_day_of_month)
        if split:
            rungs.append(split)

        rungs.append(self._payment_holiday(current_emi_paise, remaining_tenure_months))
        rungs.append(
            self._tenure_extension(
                outstanding_paise, annual_rate, remaining_tenure_months,
                current_emi_paise, current_day_of_month,
            )
        )
        rungs.append(self._formal_restructure(outstanding_paise))

        rungs.sort(key=lambda i: i.rung)

        # Withdraw rungs there is no longer time to execute. The most expensive
        # rung always survives — there is always something to offer, and an
        # empty ladder would silently become a refusal.
        if lead_time_days is not None:
            floor = lead_time_to_rung(lead_time_days)
            affordable = [i for i in rungs if i.rung >= floor]
            rungs = affordable or rungs[-1:]

        return LadderResult(recommended=rungs[0], alternatives=tuple(rungs[1:]))

    # ----------------------------------------------------------- the rungs

    @staticmethod
    def _emi_date_shift(
        profile: CustomerProfile, emi: int, current_day: int
    ) -> Intervention | None:
        """Rung 1 — the highest-leverage intervention in the system.

        Aligning the due date to when income actually arrives delivers genuine
        cash-flow relief and is ordinarily treated as a servicing change rather
        than a concession granted for financial difficulty. Real relief, at
        effectively no regulatory cost.
        """
        arrival = income_arrival_day(profile)
        if arrival is None:
            return None
        target = min(max(arrival + 2, 1), 28)
        if target == current_day:
            return None

        gap = (current_day - arrival) % 30
        return Intervention(
            rung=Rung.EMI_DATE_SHIFT,
            name="Shift the EMI date",
            description=(
                f"Move the due date from the {current_day} to the {target}, two days "
                f"after income is observed to arrive on the {arrival}. Currently the "
                f"EMI falls {gap} days before income lands."
            ),
            customer_sentence=rc.INT_EMI_DATE_SHIFT.say(
                profile.language, old=str(current_day), new=str(target)
            ),
            regulatory_cost=(
                "Ordinarily a servicing change rather than a concession for financial "
                "difficulty — no asset-classification consequence expected. VERIFY "
                "against the current circular before relying on this."
            ),
            reg_cost=RegCost.NONE,
            economic_cost_paise=0,
            reason_code=rc.INT_EMI_DATE_SHIFT.code,
            reason_params={"old": str(current_day), "new": str(target)},
            new_emi_paise=emi,
            new_day_of_month=target,
        )

    @staticmethod
    def _split_instalment(
        profile: CustomerProfile, emi: int, current_day: int
    ) -> Intervention | None:
        """Rung 2 — collect the same instalment in two parts, not one.

        Declared in the enum and reachable from ``lead_time_to_rung`` since the
        ladder was written, but never constructed, so a customer whose lead
        time selected this rung could only ever be handed the next one up.

        The full contractual instalment is still collected within the same
        billing month; nothing is deferred, reduced or rescheduled beyond it.
        That is the reason it is a servicing arrangement rather than a
        concession, and it is the rung that fits irregular income — a gig
        earner with two payouts a month cannot always meet one large debit but
        can usually meet two smaller ones.
        """
        if emi <= 0:
            return None
        arrival = income_arrival_day(profile)
        if arrival is None:
            return None
        if profile.income_type not in _SPLIT_SUITED_INCOME:
            return None

        first_half = emi // 2
        second_half = emi - first_half
        first_day = min(max(arrival + 2, 1), 28)
        second_day = ((first_day + 14 - 1) % 28) + 1

        return Intervention(
            rung=Rung.PARTIAL_PREPAYMENT_PLAN,
            name="Split the instalment",
            description=(
                f"Collect {format_inr(first_half)} on the {first_day} and "
                f"{format_inr(second_half)} on the {second_day} instead of "
                f"{format_inr(emi)} in one debit on the {current_day}. The full "
                f"instalment is still collected within the month."
            ),
            customer_sentence=(
                f"We can take your payment in two parts this month — "
                f"{format_inr(first_half)} and {format_inr(second_half)} — "
                f"instead of one."
            ),
            regulatory_cost=(
                "The full contractual instalment is collected within the same "
                "billing month, so this is ordinarily a servicing arrangement "
                "rather than a concession for financial difficulty. VERIFY "
                "against the current circular before relying on this."
            ),
            reg_cost=RegCost.NONE,
            economic_cost_paise=0,
            reason_code=rc.INT_EMI_DATE_SHIFT.code,
            reason_params={"old": str(current_day), "new": str(first_day)},
            new_emi_paise=emi,
            new_day_of_month=first_day,
        )

    @staticmethod
    def _payment_holiday(emi: int, remaining: int) -> Intervention:
        return Intervention(
            rung=Rung.SHORT_PAYMENT_HOLIDAY,
            name="Short payment holiday",
            description=(
                "One deferred instalment, recovered across the remaining schedule. "
                "Used only where the shortfall is demonstrably temporary."
            ),
            customer_sentence=(
                "We can move one month's payment to the end of your loan."
            ),
            regulatory_cost=(
                "May constitute a concession where granted for financial difficulty; "
                "classification impact must be assessed case by case."
            ),
            reg_cost=RegCost.POSSIBLE_CONCESSION,
            economic_cost_paise=int(emi * 0.08),
            reason_code=rc.INT_TENURE_EXTENSION.code,
            reason_params={"emi": format_inr(emi), "extra": format_inr(int(emi * 0.08))},
            new_emi_paise=emi,
            new_tenure_months=remaining + 1,
        )

    @staticmethod
    def _tenure_extension(
        outstanding: int, rate: float, remaining: int, current_emi: int, day: int
    ) -> Intervention:
        """Rung 4 — and never presented as a pure benefit.

        Report §9.3: the additional total cost of a longer tenure is stated in
        the Key Fact Statement, in the customer's language, before consent. The
        arithmetic is done here so the sentence can carry the real number rather
        than a vague warning.
        """
        extended = min(remaining + 12, 84)
        new_emi = emi_paise(outstanding, rate, extended) if rate > 0 else outstanding // extended
        old_total = total_cost_paise(current_emi, remaining, outstanding)
        new_total = total_cost_paise(new_emi, extended, outstanding)
        extra = max(new_total - old_total, 0)

        return Intervention(
            rung=Rung.TENURE_EXTENSION,
            name="Extend the tenure",
            description=(
                f"Extend from {remaining} to {extended} months. Monthly payment falls "
                f"from {format_inr(current_emi)} to {format_inr(new_emi)}; total cost "
                f"rises by {format_inr(extra)}."
            ),
            customer_sentence=rc.INT_TENURE_EXTENSION.say(
                "en", emi=format_inr(new_emi), extra=format_inr(extra)
            ),
            regulatory_cost=(
                "Granted on account of borrower financial difficulty this generally "
                "carries asset-classification and provisioning consequences."
            ),
            reg_cost=RegCost.DOWNGRADE_EXPECTED,
            economic_cost_paise=extra,
            reason_code=rc.INT_TENURE_EXTENSION.code,
            reason_params={"emi": format_inr(new_emi), "extra": format_inr(extra)},
            new_emi_paise=new_emi,
            new_day_of_month=day,
            new_tenure_months=extended,
            additional_total_cost_paise=extra,
        )

    @staticmethod
    def _formal_restructure(outstanding: int) -> Intervention:
        return Intervention(
            rung=Rung.FORMAL_RESTRUCTURE,
            name="Formal restructuring",
            description=(
                "Full resolution plan under the stressed-asset framework. The most "
                "expensive rung and the one the earlier rungs exist to avoid."
            ),
            customer_sentence=(
                "We can rework the whole loan, and a person will take you through "
                "what that means."
            ),
            regulatory_cost=(
                "Asset-classification downgrade and provisioning consequences apply."
            ),
            reg_cost=RegCost.DOWNGRADE_EXPECTED,
            economic_cost_paise=int(outstanding * 0.12),
            reason_code=rc.INT_TENURE_EXTENSION.code,
            reason_params={
                "emi": format_inr(0), "extra": format_inr(int(outstanding * 0.12))
            },
            reversible=False,
        )


def lead_time_to_rung(lead_time_days: int | None) -> Rung:
    """Which rung is still available, given how early the stress was detected.

    This is the function that converts model quality into money, and it is why
    report §5.3 says lead time rather than accuracy is the metric that matters.
    """
    if lead_time_days is None:
        return Rung.FORMAL_RESTRUCTURE
    if lead_time_days >= 21:
        return Rung.EMI_DATE_SHIFT
    if lead_time_days >= 10:
        return Rung.PARTIAL_PREPAYMENT_PLAN
    if lead_time_days >= 3:
        return Rung.SHORT_PAYMENT_HOLIDAY
    if lead_time_days >= 0:
        return Rung.TENURE_EXTENSION
    return Rung.FORMAL_RESTRUCTURE


DEFAULT_LADDER = InterventionLadder()
