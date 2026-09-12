"""Reason-code registry.

Report §7.6 requires one artefact rendered two ways: a regulator-grade trace and
a single spoken sentence, both derived from the same source so they cannot
drift. A reason code is that shared unit — it carries a supervisory description
*and* a customer-facing template, side by side in one record, so that adding a
reason without deciding how to say it out loud is impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Polarity(str, Enum):
    FAVOURABLE = "FAVOURABLE"
    ADVERSE = "ADVERSE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ReasonCodeSpec:
    code: str
    title: str                                  # regulator rendering
    description: str
    polarity: Polarity
    templates: dict[str, str] = field(default_factory=dict)   # customer rendering
    adverse_action: bool = False                # requires human review (§9.6)

    def say(self, lang: str = "en", **kwargs: object) -> str:
        template = self.templates.get(lang) or self.templates.get("en") or self.title
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            # A malformed substitution must never surface a raw brace to a
            # customer; fall back to the language-neutral title.
            return self.title


_R: dict[str, ReasonCodeSpec] = {}


def _reg(spec: ReasonCodeSpec) -> ReasonCodeSpec:
    _R[spec.code] = spec
    return spec


def get(code: str) -> ReasonCodeSpec:
    return _R[code]


def all_codes() -> dict[str, ReasonCodeSpec]:
    return dict(_R)


# --- Affordability, from the Financial Twin (§5.1) --------------------------

AFF_BUFFER_BREACH = _reg(ReasonCodeSpec(
    code="AFF-001",
    title="Projected balance breaches minimum safe buffer within the horizon",
    description=(
        "The Twin's six-month simulation projects the customer's balance falling "
        "below the configured safe buffer on at least one path above the "
        "breach-probability ceiling, with the candidate obligation applied."
    ),
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "Not right now — with this EMI your balance would fall below your safety buffer around {month}.",
        "hi": "अभी नहीं — इस EMI के साथ {month} के आसपास आपका बैलेंस आपके सुरक्षा बफ़र से नीचे चला जाएगा।",
    },
))

AFF_HEADROOM_OK = _reg(ReasonCodeSpec(
    code="AFF-002",
    title="Affordability cleared with retained buffer",
    description="Projected balance stays above the safe buffer on all stress scenarios tested.",
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "Your balance stays above your safety buffer every month, even if your income is late.",
        "hi": "आपकी आमदनी देर से आने पर भी हर महीने आपका बैलेंस सुरक्षा बफ़र से ऊपर रहता है।",
    },
))

AFF_SHOCK_FRAGILE = _reg(ReasonCodeSpec(
    code="AFF-003",
    title="Affordability cleared in base case but fails a tested shock scenario",
    description="Base path clears; the delayed-income or medical-shock scenario breaches the buffer.",
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "You can absorb one {shock}, but not two — so this amount is more than we would recommend.",
        "hi": "आप एक {shock} संभाल सकते हैं, दो नहीं — इसलिए यह राशि हमारी सलाह से अधिक है।",
    },
))

AFF_OTI_CEILING = _reg(ReasonCodeSpec(
    code="AFF-004",
    title="Obligation-to-income ratio exceeds policy ceiling",
    description="Existing plus proposed EMI exceeds the configured share of assessed monthly income.",
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "Your existing EMIs already take up {oti} of your monthly income.",
        "hi": "आपकी मौजूदा EMI पहले से ही आपकी मासिक आय का {oti} ले रही हैं।",
    },
))

# --- Eligibility (§5.2 step 1) ---------------------------------------------

ELG_HARD_RULE = _reg(ReasonCodeSpec(
    code="ELG-001",
    title="Hard eligibility rule not satisfied",
    description="A deterministic product policy rule (age, KYC, residency, minimum tenure) failed.",
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "This product has a requirement you do not meet yet: {rule}.",
        "hi": "इस उत्पाद की एक शर्त अभी पूरी नहीं होती: {rule}।",
    },
))

ELG_THIN_FILE_ALT_DATA = _reg(ReasonCodeSpec(
    code="ELG-002",
    title="Thin bureau file; assessed on ethically bounded alternate data",
    description=(
        "No usable bureau history. Assessment used utility payments, UPI rent, "
        "recharge regularity and SHG repayment records only (report §9.5)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "You do not have a credit history yet, so we looked at your bill and rent payments instead.",
        "hi": "आपका क्रेडिट इतिहास नहीं है, इसलिए हमने आपके बिल और किराए के भुगतान देखे।",
    },
))

# --- Recovery Mode (§6.5) ---------------------------------------------------

REC_STRESS_SUPPRESSION = _reg(ReasonCodeSpec(
    code="REC-001",
    title="Customer in Recovery Mode; all selling suppressed",
    description=(
        "Recovery-Mode state is AT_RISK or RECOVERY. No product in any family is "
        "rendered. This is the defining safeguard of the system (report §9.3)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "We are not offering you anything new while we help you get through this month.",
        "hi": "इस महीने आपकी मदद करते समय हम आपको कुछ नया नहीं दे रहे हैं।",
    },
))

REC_WATCH_PAUSE = _reg(ReasonCodeSpec(
    code="REC-002",
    title="Customer in WATCH; new credit paused without contact",
    description="Early stress indicators present. New credit offers paused; customer not contacted.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "We are keeping an eye on things and have paused new credit offers for now."},
))

# --- Conduct controls (§9.3) ------------------------------------------------

NDG_BUDGET_EXHAUSTED = _reg(ReasonCodeSpec(
    code="NDG-001",
    title="Monthly nudge budget exhausted",
    description="Contact frequency cap reached for the current calendar month.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "We have already contacted you enough this month."},
))

NDG_PRODUCT_COOLDOWN = _reg(ReasonCodeSpec(
    code="NDG-002",
    title="Per-product cooldown active",
    description="This product family was offered within the configured cooldown window.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "We showed you this recently and will not ask again so soon."},
))

NDG_DO_NOT_ASK = _reg(ReasonCodeSpec(
    code="NDG-003",
    title="Customer exercised 'do not ask me about this again'",
    description="An honoured standing preference suppresses this product family indefinitely.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "You asked us not to bring this up again."},
))

EMP_CALENDAR = _reg(ReasonCodeSpec(
    code="EMP-001",
    title="Empathy calendar suppression active",
    description="Detected bereavement, job loss or examination season suppresses offers.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "This is not a good time to be asking you about a financial product."},
))

# --- Fairness (§9.5) --------------------------------------------------------

FAI_COHORT_DRIFT = _reg(ReasonCodeSpec(
    code="FAI-001",
    title="Cohort benefit distribution outside tolerance; decision held for review",
    description=(
        "The favourable-offer rate for this customer's fairness slice diverged from "
        "the reference population beyond tolerance. Routed to human review."
    ),
    polarity=Polarity.NEUTRAL,
    adverse_action=True,
    templates={"en": "We are having a person check this before we come back to you."},
))

# --- Moment detection (§6.1) ------------------------------------------------

MOM_NO_TRIGGER = _reg(ReasonCodeSpec(
    code="MOM-001",
    title="No material change detected; silence is the correct output",
    description="The Moment Engine found no qualifying trigger. Not an error state.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "Nothing has changed that we need to talk to you about."},
))

MOM_EMI_ENDING = _reg(ReasonCodeSpec(
    code="MOM-002",
    title="Existing obligation ends within trigger window",
    description="A detected EMI series terminates within 60 days, freeing committed outflow.",
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "Your {label} finishes in {days} days, which frees up {amount} a month.",
        "hi": "आपका {label} {days} दिनों में पूरा हो रहा है, जिससे हर महीने {amount} बच जाएंगे।",
    },
))

MOM_HIGH_COST_OUTFLOW = _reg(ReasonCodeSpec(
    code="MOM-003",
    title="Outflow detected to a high-interest lending application",
    description="Repeated debits to a counterparty classified as a high-cost lender.",
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "You are paying {rate} elsewhere. We can offer the same amount at {our_rate}.",
        "hi": "आप कहीं और {rate} दे रहे हैं। हम वही राशि {our_rate} पर दे सकते हैं।",
    },
))

MOM_INCOME_RISE = _reg(ReasonCodeSpec(
    code="MOM-004",
    title="Sustained income increase detected with healthy buffer",
    description="Salary series changepoint upward, sustained three cycles, buffer already adequate.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "Your income went up and your buffer is healthy — this is a good moment to save more."},
))

MOM_PROTECTION_GAP = _reg(ReasonCodeSpec(
    code="MOM-005",
    title="Protection gap detected against observed obligations",
    description="Dependants and obligations present with no detected cover of the relevant type.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "You support {dependants} people and have no cover for them."},
))

MOM_IDLE_SURPLUS = _reg(ReasonCodeSpec(
    code="MOM-006",
    title="Idle surplus held in savings beyond threshold period",
    description="Balance persistently above buffer plus threshold for three or more months.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "You have kept {amount} idle for {months} months."},
))

MOM_SEASONAL_WINDOW = _reg(ReasonCodeSpec(
    code="MOM-007",
    title="Seasonal input window approaching for agricultural profile",
    description="Sowing window approaching on an AGRICULTURAL income profile.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "Sowing season is close. Repayment can be timed to your harvest."},
))

# --- Sentinel (§6.3, §6.4) --------------------------------------------------

SEN_STRESS_PREDICTED = _reg(ReasonCodeSpec(
    code="SEN-001",
    title="Pre-delinquency stress predicted; PD uplift over 90 days",
    description=(
        "Reported as a probability-of-default uplift so existing risk systems can "
        "consume it directly rather than as a proprietary score (report §6.3)."
    ),
    polarity=Polarity.ADVERSE,
    templates={"en": "Your next EMI falls {days} days before your income usually arrives."},
))

SEN_CORRELATED_EMPLOYER = _reg(ReasonCodeSpec(
    code="SEN-002",
    title="Correlated portfolio stress: shared employer payroll delay",
    description=(
        "Salary-credit timing grouped by employer shows a cluster deviation. This is "
        "one payroll event, not N independent borrower events (report §6.3)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={"en": "Your salary has not arrived on its usual date."},
))

SEN_FRAUD_HOLD = _reg(ReasonCodeSpec(
    code="SEN-003",
    title="Fraud pattern matched; cooling-off hold applied",
    description="Device, beneficiary-novelty and velocity features matched a Table 4 pattern.",
    polarity=Polarity.ADVERSE,
    templates={
        "en": "This transfer is on hold for {minutes} minutes. You can cancel it. We will never ask you for an OTP or PIN.",
        "hi": "यह ट्रांसफ़र {minutes} मिनट के लिए रोका गया है। आप इसे रद्द कर सकते हैं। हम कभी OTP या PIN नहीं मांगेंगे।",
    },
))

SEN_BENIGN_CHANGE = _reg(ReasonCodeSpec(
    code="SEN-004",
    title="Deviation attributed to benign life change",
    description="Pattern deviation explained by relocation, family event or seasonal norm.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "Your spending changed, but it looks like a life change rather than a problem."},
))

SEN_UNWILLING = _reg(ReasonCodeSpec(
    code="SEN-005",
    title="Non-payment with healthy balance and sustained discretionary spend",
    description=(
        "Ability-versus-willingness separation indicates unwillingness. Forbearance "
        "is withheld and the account routes to standard recovery (report §6.3)."
    ),
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={"en": "We were not able to confirm a hardship on this account."},
))

# --- Intervention ladder (§5.3) ---------------------------------------------

INT_EMI_DATE_SHIFT = _reg(ReasonCodeSpec(
    code="INT-001",
    title="EMI date shift proposed (servicing change, not a concession)",
    description=(
        "Aligning the due date to observed income arrival. Ordinarily treated as a "
        "servicing change rather than a concession granted for financial difficulty — "
        "real relief at effectively no regulatory cost (report §5.3). "
        "STATUS: design hypothesis, to be verified against current RBI circulars."
    ),
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "We can move your EMI from the {old} to the {new} — after your income arrives. Nothing else changes.",
        "hi": "हम आपकी EMI {old} से {new} कर सकते हैं — आपकी आमदनी आने के बाद। और कुछ नहीं बदलेगा।",
    },
))

INT_TENURE_EXTENSION = _reg(ReasonCodeSpec(
    code="INT-002",
    title="Tenure extension proposed (carries classification consequences)",
    description=(
        "Higher rung on the Intervention Ladder. Granted on account of borrower "
        "financial difficulty this generally carries asset-classification and "
        "provisioning consequences; the additional total cost is disclosed to the "
        "customer before consent (report §9.3)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "A longer tenure lowers the monthly payment to {emi}, but you would pay {extra} more overall.",
        "hi": "लंबी अवधि से मासिक किस्त {emi} हो जाएगी, लेकिन कुल मिलाकर आप {extra} अधिक देंगे।",
    },
))

# --- Profitability / structuring (§10.1) ------------------------------------

PRF_TWIN_SAFE_EXPOSURE = _reg(ReasonCodeSpec(
    code="PRF-001",
    title="Amount set at Twin-safe exposure rather than maximum eligibility",
    description=(
        "Default system behaviour, not an exception: limits are sized to what the "
        "simulation sustains, not to the largest approvable figure (report §5.2)."
    ),
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "You are eligible for {eligible}. We recommend {recommended}, because that is what your cash flow carries comfortably.",
        "hi": "आप {eligible} के पात्र हैं। हम {recommended} की सलाह देते हैं, क्योंकि आपका कैश फ़्लो इतना आराम से संभाल लेगा।",
    },
))

PRF_DATE_ALIGNED = _reg(ReasonCodeSpec(
    code="PRF-002",
    title="Repayment date aligned to observed income arrival",
    description="EMI date selected to fall shortly after the detected income credit date.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "Your EMI is set for the {day}, two days after your income usually arrives."},
))

# --- Counterfactual (§5.1) --------------------------------------------------

CFA_AVAILABLE = _reg(ReasonCodeSpec(
    code="CFA-001",
    title="Counterfactual structure computed",
    description=(
        "The Twin never merely refuses. This code carries the exact structure at "
        "which the declined product becomes affordable."
    ),
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "At {amount} over {tenure} months it would work — that is {emi} a month.",
        "hi": "{amount} की राशि {tenure} महीनों में संभव है — यानी हर महीने {emi}।",
    },
))
