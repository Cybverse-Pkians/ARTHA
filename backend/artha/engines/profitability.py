"""The Profitability Engine.

Report §10. The commercial argument is deliberately not an appeal to goodwill:
a bank does not maximise loans issued, it maximises interest income multiplied
by the probability of repayment, less expected losses, collection costs and
regulatory exposure.

This module implements that objective literally. It chooses the amount, tenure
and repayment date that maximise risk-adjusted lifetime value **subject to the
Twin clearing the structure** — the constraint is applied by construction, so
there is no configuration in which the optimiser can buy profit with
affordability.

Report §10.1's first lever is the one that matters most: structuring correctly
at origination applies to the entire book and carries no regulatory cost at all,
because structuring a new loan correctly is simply underwriting. The worked
example in the report — ₹6,200 over 18 months breaking the buffer where ₹4,050
over 30 months due two days after income arrives does not — is exactly what
:meth:`ProfitabilityEngine.structure` searches for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..core.money import emi_paise, total_cost_paise
from ..core.types import CustomerProfile, IncomeType
from ..features.builder import income_arrival_day
from ..products.catalogue import Product, ProductOffer
from .twin import FinancialTwin, Obligation, TwinResult, TwinVerdict

# Illustrative cost parameters (report §11.2: not measured results).
COST_OF_FUNDS = 0.065
SERVICING_COST_PER_MONTH_PAISE = 45 * 100
COLLECTION_COST_ON_DEFAULT_PAISE = 4_500 * 100
LGD = 0.65                                  # loss given default


@dataclass(frozen=True)
class StructureCandidate:
    amount_paise: int
    tenure_months: int
    emi_paise: int
    day_of_month: int
    pd_12m: float
    risk_adjusted_profit_paise: int
    twin: TwinResult

    @property
    def affordable(self) -> bool:
        return self.twin.verdict is TwinVerdict.AFFORDABLE


class ProfitabilityEngine:
    def __init__(self, twin: FinancialTwin | None = None) -> None:
        self.twin = twin or FinancialTwin()

    # ------------------------------------------------------------------ API

    def structure(
        self,
        profile: CustomerProfile,
        product: Product,
        *,
        requested_amount_paise: int | None = None,
        as_of: date | None = None,
    ) -> ProductOffer | None:
        """Choose amount, tenure and EMI date.

        Returns ``None`` when no structure clears the Twin at any tenure — which
        is a valid and important outcome, and the caller is expected to fall
        through to a counterfactual or an emergency-fund plan rather than to
        relax the constraint.
        """
        as_of = as_of or date.today()
        eligible = self.maximum_eligible_paise(profile, product)
        if eligible < product.min_amount_paise:
            return None

        target = min(requested_amount_paise or eligible, eligible)
        day = self.repayment_day(profile)

        best: StructureCandidate | None = None
        for tenure in product.tenures:
            candidate = self._best_amount_for_tenure(
                profile, product, tenure, day, target, as_of
            )
            if candidate is None:
                continue
            if best is None or candidate.risk_adjusted_profit_paise > best.risk_adjusted_profit_paise:
                best = candidate

        if best is None:
            return None

        return ProductOffer(
            product=product,
            amount_paise=best.amount_paise,
            eligible_amount_paise=eligible,
            tenure_months=best.tenure_months,
            emi_paise=best.emi_paise,
            day_of_month=best.day_of_month,
            annual_rate=product.annual_rate,
            total_interest_paise=total_cost_paise(
                best.emi_paise, best.tenure_months, best.amount_paise
            ),
            rationale=self._rationale(best, eligible),
        )

    def repayment_day(self, profile: CustomerProfile) -> int:
        """Place the EMI date shortly *after* income actually arrives.

        This is the highest-leverage single decision the engine makes. Report
        §5.3 identifies aligning the due date to observed income as real
        cash-flow relief at effectively no regulatory cost; doing it at
        origination costs nothing at all, because it is simply underwriting.
        """
        arrival = income_arrival_day(profile)
        if arrival is None:
            return 7
        return min(max(arrival + 2, 1), 28)

    def maximum_eligible_paise(self, profile: CustomerProfile, product: Product) -> int:
        """Policy maximum — the figure the customer is *eligible* for.

        Retained and shown alongside the recommendation (report §5.2). Being
        told "you are eligible for ₹5 lakh, and we recommend ₹2.5 lakh" is the
        system's default behaviour, and it requires knowing both numbers.
        """
        if product.annual_rate <= 0:
            return product.max_amount_paise

        # Conventional multiple-of-income eligibility, capped by product policy.
        headroom = max(
            profile.monthly_income_paise * 0.50 - profile.existing_emi_paise, 0
        )
        longest = max(product.tenures)
        affordable_principal = self._principal_for_emi(
            int(headroom), product.annual_rate, longest
        )
        return int(min(max(affordable_principal, 0), product.max_amount_paise))

    # ----------------------------------------------------------- internals

    def _best_amount_for_tenure(
        self,
        profile: CustomerProfile,
        product: Product,
        tenure: int,
        day: int,
        target: int,
        as_of: date,
    ) -> StructureCandidate | None:
        """Largest Twin-clearing amount at this tenure, by bisection."""
        lo, hi = product.min_amount_paise, target
        best: StructureCandidate | None = None

        probe = self._evaluate(profile, product, lo, tenure, day, as_of)
        if not probe.affordable:
            return None                       # even the minimum breaks the buffer

        best = probe
        for _ in range(10):
            mid = (lo + hi) // 2
            if mid <= lo:
                break
            candidate = self._evaluate(profile, product, mid, tenure, day, as_of)
            if candidate.affordable:
                best, lo = candidate, mid
            else:
                hi = mid
        return best

    def _evaluate(
        self,
        profile: CustomerProfile,
        product: Product,
        amount: int,
        tenure: int,
        day: int,
        as_of: date,
    ) -> StructureCandidate:
        emi = (
            emi_paise(amount, product.annual_rate, tenure)
            if product.annual_rate > 0 else amount // max(tenure, 1)
        )
        obligation = Obligation(
            label=product.name, emi_paise=emi, day_of_month=day,
            tenure_months=tenure, principal_paise=amount, annual_rate=product.annual_rate,
        )
        twin = self.twin.simulate(profile, obligation, as_of=as_of)
        pd = self.probability_of_default(profile, twin, tenure)
        profit = self.risk_adjusted_profit_paise(amount, emi, tenure, product.annual_rate, pd)
        return StructureCandidate(amount, tenure, emi, day, pd, profit, twin)

    @staticmethod
    def probability_of_default(
        profile: CustomerProfile, twin: TwinResult, tenure_months: int
    ) -> float:
        """A 12-month PD estimate driven by the simulation, not by a score alone.

        Illustrative and deliberately simple. The point is the *shape*: PD falls
        as the Twin's resilience rises, rises with obligation-to-income and with
        income volatility, and is floored so that no structure is ever treated
        as riskless. In deployment this is the gradient-boosted PD model of
        report §8, and the Twin's resilience becomes one of its features.
        """
        base = 0.055
        resilience_factor = 1.0 - (twin.resilience_score / 100.0) * 0.75
        oti_factor = 1.0 + max(profile.obligation_to_income - 0.25, 0) * 2.2
        volatility_factor = 1.0 + min(profile.income_volatility, 1.0) * 0.45
        tenure_factor = 1.0 + (tenure_months / 60.0) * 0.25
        thin_file_factor = 1.12 if profile.thin_file else 1.0

        pd = base * resilience_factor * oti_factor * volatility_factor * tenure_factor
        pd *= thin_file_factor
        if twin.verdict is TwinVerdict.FRAGILE:
            pd *= 1.6
        elif twin.verdict is TwinVerdict.UNAFFORDABLE:
            pd *= 3.0
        return float(min(max(pd, 0.004), 0.85))

    @staticmethod
    def risk_adjusted_profit_paise(
        amount: int, emi: int, tenure: int, annual_rate: float, pd: float
    ) -> int:
        """Interest income × probability of repayment, less losses and costs.

        The arithmetic report §10 sets out. Expected loss uses a mid-life
        default assumption — a loan that defaults does so with roughly half its
        principal still outstanding — which is crude but keeps the sign of the
        trade-off right: longer tenures earn more interest and carry more
        default exposure, and the optimiser has to weigh both.
        """
        gross_interest = max(emi * tenure - amount, 0)
        funding_cost = int(amount * COST_OF_FUNDS * (tenure / 12.0) * 0.5)
        servicing = SERVICING_COST_PER_MONTH_PAISE * tenure

        exposure_at_default = amount * 0.5
        expected_loss = pd * exposure_at_default * LGD
        expected_collection = pd * COLLECTION_COST_ON_DEFAULT_PAISE

        profit = (
            gross_interest * (1 - pd)
            - funding_cost
            - servicing
            - expected_loss
            - expected_collection
        )
        return int(profit)

    @staticmethod
    def _principal_for_emi(emi: int, annual_rate: float, tenure: int) -> int:
        """Invert the EMI formula."""
        if emi <= 0 or tenure <= 0:
            return 0
        r = annual_rate / 12.0
        if r <= 0:
            return emi * tenure
        factor = (1 + r) ** tenure
        return int(emi * (factor - 1) / (r * factor))

    @staticmethod
    def _rationale(best: StructureCandidate, eligible: int) -> str:
        parts = [
            f"Tenure {best.tenure_months}m chosen by risk-adjusted profit "
            f"(PD {best.pd_12m:.1%}, resilience {best.twin.resilience_score:.0f}/100).",
            f"EMI dated the {best.day_of_month} to follow income arrival.",
        ]
        if best.amount_paise < eligible:
            parts.append(
                "Amount set at Twin-safe exposure rather than maximum eligibility."
            )
        return " ".join(parts)


def seasonal_repayment_note(profile: CustomerProfile) -> str | None:
    """Agricultural and seasonal profiles do not have a monthly capacity.

    Report §6.1 routes them to a facility repaid at harvest. Saying so where the
    structure is built keeps the exception visible to whoever reads this code
    next, rather than leaving it to the catalogue's ``requires_monthly_repayment``
    flag alone.
    """
    if profile.income_type in {IncomeType.AGRICULTURAL, IncomeType.SEASONAL}:
        return (
            "Income arrives in bursts; a fixed monthly EMI is the wrong instrument. "
            "Repayment should be timed to the next income window."
        )
    return None


DEFAULT_ENGINE = ProfitabilityEngine()
