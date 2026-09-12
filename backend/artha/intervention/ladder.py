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
from ..core.types import CustomerProfile, PayIntent
from ..features.builder import income_arrival_day


class Rung(IntEnum):
    """Ordered by cost. Lower is cheaper and is always tried first."""

    EMI_DATE_SHIFT = 1
    PARTIAL_PREPAYMENT_PLAN = 2
    SHORT_PAYMENT_HOLIDAY = 3
    TENURE_EXTENSION = 4
    FORMAL_RESTRUCTURE = 5
    RECOVERY = 6


@dataclass(frozen=True)
class Intervention:
    rung: Rung
    name: str
    description: str
    customer_sentence: str
    regulatory_cost: str
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
        as_of: date | None = None,
    ) -> LadderResult:
        """Build the ladder and recommend the lowest rung that actually helps.

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

        rungs.append(self._payment_holiday(current_emi_paise, remaining_tenure_months))
        rungs.append(
            self._tenure_extension(
                outstanding_paise, annual_rate, remaining_tenure_months,
                current_emi_paise, current_day_of_month,
            )
        )
        rungs.append(self._formal_restructure(outstanding_paise))

        rungs.sort(key=lambda i: i.rung)
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
            economic_cost_paise=0,
            reason_code=rc.INT_EMI_DATE_SHIFT.code,
            reason_params={"old": str(current_day), "new": str(target)},
            new_emi_paise=emi,
            new_day_of_month=target,
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
