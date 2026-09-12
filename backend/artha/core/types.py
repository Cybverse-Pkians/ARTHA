"""Shared vocabulary for ARTHA.

These enums are the seams between engines. They matter more than they look:
report §7.7 requires that transaction narrations — which are attacker-controlled
text — reach the language model only as *typed, enum-constrained values*. That
guarantee is only as good as the discipline of passing these types around
instead of strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class Direction(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class Channel(str, Enum):
    UPI = "UPI"
    NEFT = "NEFT"
    IMPS = "IMPS"
    ACH = "ACH"          # mandates, EMI auto-debits
    CARD = "CARD"
    CASH = "CASH"
    CHEQUE = "CHEQUE"
    INTERNAL = "INTERNAL"


class Category(str, Enum):
    """Bharat Transaction Ontology leaf categories."""

    SALARY = "SALARY"
    GIG_PAYOUT = "GIG_PAYOUT"
    AGRI_PROCEEDS = "AGRI_PROCEEDS"
    BUSINESS_RECEIPTS = "BUSINESS_RECEIPTS"
    GOVT_BENEFIT = "GOVT_BENEFIT"
    INTEREST_INCOME = "INTEREST_INCOME"
    REMITTANCE_IN = "REMITTANCE_IN"

    RENT = "RENT"
    EMI = "EMI"
    INSURANCE_PREMIUM = "INSURANCE_PREMIUM"
    UTILITIES = "UTILITIES"
    TELECOM = "TELECOM"
    SUBSCRIPTION = "SUBSCRIPTION"
    GROCERIES = "GROCERIES"
    FUEL = "FUEL"
    TRANSPORT = "TRANSPORT"
    HEALTHCARE = "HEALTHCARE"
    PHARMACY = "PHARMACY"
    EDUCATION = "EDUCATION"
    APPAREL = "APPAREL"
    DINING = "DINING"
    ENTERTAINMENT = "ENTERTAINMENT"
    TRAVEL = "TRAVEL"
    FESTIVAL = "FESTIVAL"
    AGRI_INPUT = "AGRI_INPUT"
    INVESTMENT_OUT = "INVESTMENT_OUT"
    SAVINGS_TRANSFER = "SAVINGS_TRANSFER"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    P2P_TRANSFER = "P2P_TRANSFER"
    HIGH_COST_CREDIT = "HIGH_COST_CREDIT"   # BNPL / app lenders — a trigger, §6.1
    GAMBLING = "GAMBLING"
    UNCLASSIFIED = "UNCLASSIFIED"


INCOME_CATEGORIES = frozenset({
    Category.SALARY, Category.GIG_PAYOUT, Category.AGRI_PROCEEDS,
    Category.BUSINESS_RECEIPTS, Category.GOVT_BENEFIT,
    Category.INTEREST_INCOME, Category.REMITTANCE_IN,
})

COMMITTED_OUTFLOW_CATEGORIES = frozenset({
    Category.RENT, Category.EMI, Category.INSURANCE_PREMIUM,
    Category.UTILITIES, Category.TELECOM, Category.SUBSCRIPTION,
    Category.EDUCATION,
})

DISCRETIONARY_CATEGORIES = frozenset({
    Category.DINING, Category.ENTERTAINMENT, Category.TRAVEL,
    Category.APPAREL, Category.FESTIVAL,
})


class IncomeType(str, Enum):
    """The single label that reconfigures every downstream model (report §4.2).

    A farmer with no income for four months is normal; a salaried customer with
    the same pattern is in crisis. Nothing else in the system carries as much
    weight per bit, which is why §11.3 names its misclassification as a top
    limitation and §5.1 makes the human override path mandatory.
    """

    SALARIED_STABLE = "SALARIED_STABLE"
    SALARIED_VOLATILE = "SALARIED_VOLATILE"
    GIG = "GIG"
    SEASONAL = "SEASONAL"
    AGRICULTURAL = "AGRICULTURAL"
    BUSINESS = "BUSINESS"
    UNKNOWN = "UNKNOWN"


class FinancialPosture(str, Enum):
    """Report §7.3 — segments that map onto Recovery Mode states."""

    BUFFER_BUILDING = "BUFFER_BUILDING"
    STEADY = "STEADY"
    LEVERAGED = "LEVERAGED"
    OVER_EXTENDED = "OVER_EXTENDED"
    RECOVERING = "RECOVERING"


class ChannelSegment(str, Enum):
    """Drives the delivery ladder, never the product choice (report §7.3)."""

    APP_NATIVE = "APP_NATIVE"
    ASSISTED = "ASSISTED"
    VOICE_ONLY = "VOICE_ONLY"
    FEATURE_PHONE = "FEATURE_PHONE"


class ProductFamily(str, Enum):
    LOAN = "LOAN"
    INSURANCE = "INSURANCE"
    INVESTMENT = "INVESTMENT"
    CREDIT_CARD = "CREDIT_CARD"
    SAVINGS = "SAVINGS"
    RESTRUCTURE = "RESTRUCTURE"


class GateOutcome(str, Enum):
    """The four outcomes the Gate may emit (report §4.3)."""

    ACT = "ACT"                # speak to the customer
    SUPPRESS = "SUPPRESS"      # say nothing; this is a success, not a failure
    PROTECT = "PROTECT"        # stress or fraud path — assist, never sell
    VERIFY = "VERIFY"          # step-up authentication or human review first


class RecoveryState(str, Enum):
    """Reversible state machine of report §6.5."""

    STABLE = "STABLE"
    WATCH = "WATCH"            # monitor, pause new credit, do not contact
    AT_RISK = "AT_RISK"        # offer options
    RECOVERY = "RECOVERY"      # suppress all marketing, track plan, human support


class SentinelVerdict(str, Enum):
    """Report §6.4 / Figure 7 — the three-way separation that drives routing."""

    BENIGN_LIFE_CHANGE = "BENIGN_LIFE_CHANGE"
    FINANCIAL_DISTRESS = "FINANCIAL_DISTRESS"
    FRAUD = "FRAUD"
    NORMAL = "NORMAL"


class PayIntent(str, Enum):
    """Inability and unwillingness are different problems with opposite
    responses (report §6.3). Forbearance for hardship is portfolio
    optimisation; forbearance for strategic default is a giveaway."""

    UNABLE = "UNABLE"
    UNWILLING = "UNWILLING"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class Transaction:
    """A raw transaction as it arrives from core banking CDC.

    ``narration`` is untrusted. A payer controls their own VPA display name and
    remarks string, so this field is an injection vector and is treated as one
    everywhere downstream (report §7.7).
    """

    txn_id: str
    customer_token: str
    ts: datetime
    amount_paise: int              # signed: negative is a debit
    narration: str
    channel: Channel = Channel.UPI
    balance_after_paise: int | None = None
    counterparty_vpa: str | None = None
    counterparty_name: str | None = None

    @property
    def direction(self) -> Direction:
        return Direction.CREDIT if self.amount_paise >= 0 else Direction.DEBIT

    @property
    def magnitude_paise(self) -> int:
        return abs(self.amount_paise)

    @property
    def value_date(self) -> date:
        return self.ts.date()


@dataclass(frozen=True)
class Merchant:
    merchant_id: str
    display_name: str
    category: Category
    is_high_cost_lender: bool = False


@dataclass(frozen=True)
class EnrichedTransaction:
    """A transaction after the Bharat Transaction Ontology has parsed it.

    Note what survives: typed values and a confidence. The original narration is
    retained for audit, but nothing downstream is permitted to interpret it, and
    it never reaches the language model.
    """

    txn: Transaction
    category: Category
    merchant: Merchant | None = None
    counterparty_key: str | None = None
    is_recurring: bool = False
    series_id: str | None = None
    confidence: float = 1.0
    parser: str = "rules"          # rules | ngram | fallback

    @property
    def direction(self) -> Direction:
        return self.txn.direction

    @property
    def amount_paise(self) -> int:
        return self.txn.amount_paise

    @property
    def value_date(self) -> date:
        return self.txn.value_date


@dataclass(frozen=True)
class RecurringSeries:
    """A detected recurring obligation or income stream.

    ``evidence_dates`` exists because report §7.1 requires that the supporting
    dates be showable to a regulator. A recurrence claim without its evidence is
    not auditable.
    """

    series_id: str
    category: Category
    direction: Direction
    median_amount_paise: int
    period_days: int
    day_of_month: int | None
    last_seen: date
    occurrences: int
    amount_volatility: float           # coefficient of variation
    evidence_dates: tuple[date, ...] = field(default_factory=tuple)
    label: str = ""
    drifting: bool = False             # changepoint detected in the amount series


@dataclass(frozen=True)
class CustomerProfile:
    """Everything the engines need about a customer, already consent-scoped.

    Constructed by the feature store; engines never reach past this to raw data.
    """

    customer_token: str
    language: str = "hi"
    channel_segment: ChannelSegment = ChannelSegment.APP_NATIVE
    income_type: IncomeType = IncomeType.UNKNOWN
    income_type_confidence: float = 0.0
    income_type_overridden: bool = False        # a human corrected it — §5.1
    posture: FinancialPosture = FinancialPosture.STEADY
    recovery_state: RecoveryState = RecoveryState.STABLE

    balance_paise: int = 0
    monthly_income_paise: int = 0
    income_volatility: float = 0.0
    monthly_committed_outflow_paise: int = 0
    monthly_discretionary_paise: int = 0
    existing_emi_paise: int = 0

    age: int | None = None
    dependants: int = 0
    has_term_cover: bool = False
    has_health_cover: bool = False
    credit_utilisation: float = 0.0
    bureau_score: int | None = None
    thin_file: bool = False
    district: str = ""
    is_rural: bool = False
    employer_id: str | None = None

    series: tuple[RecurringSeries, ...] = field(default_factory=tuple)

    # Observed income timing, computed at feature-build time from the raw
    # credits. Kept on the profile because the Intervention Ladder's cheapest
    # rung depends on it and must not fail merely because periodicity detection
    # did not fire on an irregular payroll.
    income_day_of_month: int | None = None
    income_day_dispersion: float = 0.0

    tenure_with_bank_months: int = 0
    on_time_emi_streak: int = 0

    @property
    def disposable_income_paise(self) -> int:
        return max(
            0,
            self.monthly_income_paise
            - self.monthly_committed_outflow_paise
            - self.monthly_discretionary_paise,
        )

    @property
    def obligation_to_income(self) -> float:
        if self.monthly_income_paise <= 0:
            return 1.0
        return self.existing_emi_paise / self.monthly_income_paise
