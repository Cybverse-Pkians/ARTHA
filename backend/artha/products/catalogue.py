"""Product catalogue and offer construction.

The catalogue is data, not logic. It is the bank's own product master, and
report §8.1 makes a point of the feedback loop it enables: ARTHA reports back
which product *terms* most frequently cause suitability rejections, which turns
the system into a catalogue-optimisation tool rather than a critic.

Every product carries its hard eligibility rules as explicit, named predicates.
Naming them matters — a rejected customer is entitled to be told which rule they
did not meet (reason code ELG-001), and an unnamed lambda cannot be shown to
anyone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..core.money import rupees
from ..core.types import CustomerProfile, IncomeType, ProductFamily


@dataclass(frozen=True)
class EligibilityRule:
    name: str
    description: str
    predicate: Callable[[CustomerProfile], bool]

    def check(self, profile: CustomerProfile) -> bool:
        try:
            return bool(self.predicate(profile))
        except Exception:
            # A rule that errors must fail closed. Silently passing a broken
            # eligibility check is how an ineligible customer gets an offer.
            return False


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    family: ProductFamily
    min_amount_paise: int
    max_amount_paise: int
    annual_rate: float                        # 0.0 for non-credit products
    tenures: tuple[int, ...]
    rules: tuple[EligibilityRule, ...] = field(default_factory=tuple)
    description: str = ""
    replaces_high_cost: bool = False          # counter-offer candidate, §6.1
    requires_monthly_repayment: bool = True

    def failing_rules(self, profile: CustomerProfile) -> list[EligibilityRule]:
        return [r for r in self.rules if not r.check(profile)]


# --- reusable rules ---------------------------------------------------------

def _min_age(n: int) -> EligibilityRule:
    return EligibilityRule(
        f"min_age_{n}", f"Applicant must be at least {n} years old",
        lambda p: p.age is not None and p.age >= n,
    )


def _max_age(n: int) -> EligibilityRule:
    return EligibilityRule(
        f"max_age_{n}", f"Applicant must be under {n} at maturity",
        lambda p: p.age is not None and p.age <= n,
    )


def _min_income(rupee_amount: int) -> EligibilityRule:
    return EligibilityRule(
        f"min_income_{rupee_amount}",
        f"Assessed monthly income must be at least ₹{rupee_amount:,}",
        lambda p: p.monthly_income_paise >= rupees(rupee_amount),
    )


def _min_relationship(months: int) -> EligibilityRule:
    return EligibilityRule(
        f"min_relationship_{months}m",
        f"Account relationship of at least {months} months",
        lambda p: p.tenure_with_bank_months >= months,
    )


def _income_type_in(*types: IncomeType) -> EligibilityRule:
    names = ", ".join(t.value for t in types)
    return EligibilityRule(
        "income_type", f"Available to income profiles: {names}",
        lambda p: p.income_type in set(types),
    )


_OTI_HEADROOM = EligibilityRule(
    "oti_headroom",
    "Existing EMIs must leave headroom under the obligation-to-income ceiling",
    lambda p: p.obligation_to_income < 0.45,
)

_NOT_OVER_UTILISED = EligibilityRule(
    "utilisation", "Revolving credit utilisation must be below 80%",
    lambda p: p.credit_utilisation < 0.80,
)


# --- the catalogue ----------------------------------------------------------

CATALOGUE: tuple[Product, ...] = (
    Product(
        product_id="pl_standard",
        name="Personal loan",
        family=ProductFamily.LOAN,
        min_amount_paise=rupees(25_000),
        max_amount_paise=rupees(500_000),
        annual_rate=0.1450,
        tenures=(12, 18, 24, 30, 36, 48, 60),
        rules=(_min_age(21), _max_age(58), _min_income(15_000), _min_relationship(6), _OTI_HEADROOM),
        description="Unsecured personal loan for a stated purpose.",
    ),
    Product(
        product_id="pl_topup",
        name="Pre-approved top-up",
        family=ProductFamily.LOAN,
        min_amount_paise=rupees(20_000),
        max_amount_paise=rupees(300_000),
        annual_rate=0.1325,
        tenures=(12, 18, 24, 36),
        rules=(_min_age(21), _max_age(58), _min_relationship(12), _OTI_HEADROOM),
        description="Top-up offered as an existing obligation ends.",
    ),
    Product(
        product_id="gold_loan",
        name="Gold loan",
        family=ProductFamily.LOAN,
        min_amount_paise=rupees(20_000),
        max_amount_paise=rupees(400_000),
        annual_rate=0.0925,
        tenures=(6, 12, 18, 24),
        rules=(_min_age(21),),
        description="Secured against gold; materially cheaper than app lending.",
        replaces_high_cost=True,
    ),
    Product(
        product_id="od_deposit",
        name="Overdraft against deposit",
        family=ProductFamily.LOAN,
        min_amount_paise=rupees(10_000),
        max_amount_paise=rupees(200_000),
        annual_rate=0.0875,
        tenures=(12, 24),
        rules=(_min_age(18), _min_relationship(6)),
        description="Overdraft secured by an existing term deposit.",
        replaces_high_cost=True,
    ),
    Product(
        product_id="crop_facility",
        name="Crop facility",
        family=ProductFamily.LOAN,
        min_amount_paise=rupees(15_000),
        max_amount_paise=rupees(250_000),
        annual_rate=0.0700,
        tenures=(6, 9, 12),
        rules=(_min_age(18), _income_type_in(IncomeType.AGRICULTURAL, IncomeType.SEASONAL)),
        description="Disbursed at sowing, repaid at harvest.",
        requires_monthly_repayment=False,
    ),
    Product(
        product_id="health_cover",
        name="Health cover",
        family=ProductFamily.INSURANCE,
        min_amount_paise=rupees(300),
        max_amount_paise=rupees(2_500),
        annual_rate=0.0,
        tenures=(12,),
        rules=(_min_age(18), _max_age(65)),
        description="Premium sized to observed medical outflow.",
    ),
    Product(
        product_id="term_life",
        name="Term life cover",
        family=ProductFamily.INSURANCE,
        min_amount_paise=rupees(400),
        max_amount_paise=rupees(3_000),
        annual_rate=0.0,
        tenures=(12,),
        rules=(_min_age(18), _max_age(60)),
        description="Sum assured derived from actual obligations, not a round number.",
    ),
    Product(
        product_id="sip",
        name="Systematic investment plan",
        family=ProductFamily.INVESTMENT,
        min_amount_paise=rupees(500),
        max_amount_paise=rupees(25_000),
        annual_rate=0.0,
        tenures=(12, 24, 36),
        rules=(_min_age(18),),
        description="Monthly investment; increased only when the buffer is already healthy.",
    ),
    Product(
        product_id="recurring_deposit",
        name="Recurring deposit",
        family=ProductFamily.INVESTMENT,
        min_amount_paise=rupees(500),
        max_amount_paise=rupees(50_000),
        annual_rate=0.0,
        tenures=(12, 24, 36, 60),
        rules=(_min_age(18),),
        description="Sized so the safe buffer is preserved, never consumed.",
    ),
    Product(
        product_id="credit_card",
        name="Credit card",
        family=ProductFamily.CREDIT_CARD,
        min_amount_paise=rupees(15_000),
        max_amount_paise=rupees(300_000),
        annual_rate=0.36,
        tenures=(1,),
        rules=(_min_age(21), _min_income(20_000), _min_relationship(12),
               _NOT_OVER_UTILISED, _OTI_HEADROOM),
        description="Limit set at Twin-safe exposure, not at maximum eligibility.",
    ),
    Product(
        product_id="emergency_fund",
        name="Emergency fund plan",
        family=ProductFamily.SAVINGS,
        min_amount_paise=rupees(200),
        max_amount_paise=rupees(10_000),
        annual_rate=0.0,
        tenures=(6, 12),
        rules=(),
        description=(
            "Not a credit product. The correct recommendation when the Twin "
            "finds no affordable structure at any tenure."
        ),
    ),
)

BY_ID: dict[str, Product] = {p.product_id: p for p in CATALOGUE}


def by_family(family: ProductFamily) -> list[Product]:
    return [p for p in CATALOGUE if p.family is family]


@dataclass(frozen=True)
class ProductOffer:
    """A fully structured, Twin-sized offer.

    ``eligible_amount_paise`` is retained alongside ``amount_paise`` on purpose.
    Report §5.2 requires the customer to be told both — "you are eligible for
    ₹5 lakh, and we recommend ₹2.5 lakh" — and an offer object that discards the
    eligible figure cannot render that sentence.
    """

    product: Product
    amount_paise: int
    eligible_amount_paise: int
    tenure_months: int
    emi_paise: int
    day_of_month: int
    annual_rate: float
    total_interest_paise: int
    rationale: str = ""

    @property
    def is_reduced_from_eligibility(self) -> bool:
        return self.amount_paise < self.eligible_amount_paise
