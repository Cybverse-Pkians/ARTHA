"""The AI Firewall.

Report §7.7. The language model sits inside the system's blast radius and is
therefore contained by construction rather than by instruction. Four mechanisms,
each closing a specific failure mode:

1. **Narrations never reach the model.** Enforced upstream, in
   :mod:`artha.ontology.narration`: attacker-controlled text is parsed into
   typed, enum-constrained values. This module assumes that guarantee and
   re-checks it at the boundary, because a defence that is only enforced in one
   place is one refactor away from being enforced nowhere.

2. **Numeric grounding.** Every numeral in model output must match a field in
   the Decision Object or the response is blocked and a template is used
   instead. This mechanically eliminates hallucinated rates and fees.

3. **Capability tokens rather than tool access.** The model cannot call an
   approval or transfer function. It proposes; the policy engine mints a signed,
   single-use, scoped token; execution additionally requires explicit customer
   confirmation. Propose, preview, confirm, execute — the model is present only
   at the first step.

4. **No personal data reaches the model.** It receives tokenised references and
   pre-rendered amounts, so full model compromise leaks nothing identifying.

The governing rule of the whole system applies here: **the language model is the
mouth, not the brain.**
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from ..config import settings
from ..core.decision import CustomerRendering, DecisionObject

# Numerals in Latin and the major Indic digit ranges. A model answering in
# Hindi may emit Devanagari digits, and a grounding check that only understands
# ASCII would wave those through unverified.
_NUMBER_RE = re.compile(r"-?\d[\d,  ]*\.?\d*")

# Credential terms, and the assurance constructions that legitimately mention
# them. Report §6.2 requires the assistant to state *visibly* that it will never
# ask for an OTP, PIN or CVV — so the anti-phishing sentence names the very
# tokens the firewall is watching for, and it does so in the customer's own
# language.
#
# An English-only exemption ("...unless followed by the word 'never'") blocks
# ARTHA's own Hindi, Tamil and Bengali safety messages while passing an English
# phishing attempt that happens to contain the word. The markers below are
# therefore per-language, and the check is: a credential term is a violation
# *unless* an assurance marker appears in the same message.
_CREDENTIAL_RE = re.compile(
    r"\b(otp|one[- ]time password|pin|cvv|password|passcode|mpin)\b", re.I
)

_ASSURANCE_MARKERS: tuple[str, ...] = (
    # en
    "never ask", "never request", "will not ask", "do not share", "never share",
    # hi / mr
    "कभी नहीं", "नहीं मांगेंगे", "नहीं मांगते", "साझा न करें", "किसी को न बताएं",
    # bn / as
    "কখনো চাইব না", "চাইবে না", "শেয়ার করবেন না",
    # ta
    "கேட்க மாட்டோம்", "பகிர வேண்டாம்",
    # te
    "అడగము", "పంచుకోవద్దు",
    # kn
    "ಕೇಳುವುದಿಲ್ಲ", "ಹಂಚಿಕೊಳ್ಳಬೇಡಿ",
    # gu
    "ક્યારેય નહીં", "શેર કરશો નહીં",
    # ml
    "ചോദിക്കില്ല", "പങ്കിടരുത്",
    # pa
    "ਕਦੇ ਨਹੀਂ", "ਸਾਂਝਾ ਨਾ ਕਰੋ",
    # or
    "ପଚାରିବୁ ନାହିଁ", "ସେୟାର କରନ୍ତୁ ନାହିଁ",
)


def _solicits_credential(text: str) -> bool:
    if not _CREDENTIAL_RE.search(text):
        return False
    lowered = text.lower()
    return not any(marker.lower() in lowered for marker in _ASSURANCE_MARKERS)


_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("promises_approval", re.compile(
        r"\b(guaranteed|assured|pre-?approved for any|100%\s*approval|certain to be approved)\b", re.I)),
    ("manufactures_urgency", re.compile(
        r"\b(hurry|limited time|expires in|act now|last chance|only today)\b", re.I)),
    ("claims_authority", re.compile(
        r"\bi (have|hereby) (approved|sanctioned|disbursed|authorised|authorized)\b", re.I)),
)


class FirewallOutcome(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED_UNGROUNDED_NUMBER = "BLOCKED_UNGROUNDED_NUMBER"
    BLOCKED_FORBIDDEN_CONTENT = "BLOCKED_FORBIDDEN_CONTENT"
    BLOCKED_LEAKED_IDENTIFIER = "BLOCKED_LEAKED_IDENTIFIER"


@dataclass(frozen=True)
class FirewallVerdict:
    outcome: FirewallOutcome
    text: str                                   # what is actually delivered
    blocked_detail: str = ""
    ungrounded: tuple[float, ...] = field(default_factory=tuple)
    used_fallback: bool = False

    @property
    def allowed(self) -> bool:
        return self.outcome is FirewallOutcome.ALLOWED


def extract_numbers(text: str) -> list[float]:
    """Pull every numeral out of a string, Indic digits included.

    Indian grouping means thousands separators appear mid-number ("1,00,000"),
    so separators are stripped before parsing rather than treated as
    delimiters — otherwise one amount reads as three small integers and passes
    grounding trivially.
    """
    normalised = "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch
        for ch in text
    )
    out: list[float] = []
    for token in _NUMBER_RE.findall(normalised):
        cleaned = token.replace(",", "").replace(" ", "").replace(" ", "")
        cleaned = cleaned.rstrip(".")
        if not cleaned or cleaned in {"-", "."}:
            continue
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


def is_grounded(
    value: float, ground: tuple[float, ...], *, tolerance: float | None = None
) -> bool:
    """Whether one numeral traces back to a Decision Object field.

    The tolerance is **absolute**, not relative. A relative band is the intuitive
    choice and the wrong one here: at 0.5%, a model could state ₹1,00,500 against
    a ₹1,00,000 offer and pass a check whose entire purpose is to make that
    impossible. One rupee absorbs the rounding that rendering introduces and
    nothing else.
    """
    tol = tolerance if tolerance is not None else settings.firewall_numeric_tolerance_rupees
    return any(abs(value - allowed) <= tol for allowed in ground)


class AIFirewall:
    """Validates model output against the Decision Object before delivery."""

    def __init__(self, *, forbidden: tuple | None = None) -> None:
        self.forbidden = forbidden or _FORBIDDEN_PATTERNS

    def validate(
        self,
        model_text: str,
        decision: DecisionObject,
        *,
        fallback: CustomerRendering | None = None,
    ) -> FirewallVerdict:
        """Check model output; on any violation, fall back to the template.

        Falling back rather than erroring is deliberate. The customer is mid
        conversation and a refusal to speak is itself a failure; the template
        rendering is always available because it is generated from the same
        object, so there is no case in which the system has nothing safe to say.
        """
        fallback_text = (fallback or decision.render_customer()).spoken

        leaked = self._leaked_identifiers(model_text, decision)
        if leaked:
            return FirewallVerdict(
                FirewallOutcome.BLOCKED_LEAKED_IDENTIFIER, fallback_text,
                blocked_detail=f"output contained identifier-shaped token: {leaked}",
                used_fallback=True,
            )

        if _solicits_credential(model_text):
            return FirewallVerdict(
                FirewallOutcome.BLOCKED_FORBIDDEN_CONTENT, fallback_text,
                blocked_detail="forbidden pattern: solicits_credential",
                used_fallback=True,
            )

        for name, pattern in self.forbidden:
            if pattern.search(model_text):
                return FirewallVerdict(
                    FirewallOutcome.BLOCKED_FORBIDDEN_CONTENT, fallback_text,
                    blocked_detail=f"forbidden pattern: {name}",
                    used_fallback=True,
                )

        ground = decision.numeric_ground()
        ungrounded = tuple(
            n for n in extract_numbers(model_text) if not is_grounded(n, ground)
        )
        if ungrounded:
            return FirewallVerdict(
                FirewallOutcome.BLOCKED_UNGROUNDED_NUMBER, fallback_text,
                blocked_detail=(
                    f"{len(ungrounded)} numeral(s) not present in the Decision Object"
                ),
                ungrounded=ungrounded,
                used_fallback=True,
            )

        return FirewallVerdict(FirewallOutcome.ALLOWED, model_text)

    @staticmethod
    def _leaked_identifiers(text: str, decision: DecisionObject) -> str | None:
        """Catch the model echoing something that identifies the customer.

        It should never have received one. This check exists because "should
        never" is a claim about the rest of the system, and the cheapest place
        to verify it is at the exit.
        """
        if decision.customer_token and decision.customer_token in text:
            return "customer_token"
        patterns = (
            (r"\b[A-Z]{5}\d{4}[A-Z]\b", "PAN-shaped"),
            (r"\b\d{4}\s?\d{4}\s?\d{4}\b", "Aadhaar-shaped"),
            (r"\b[a-z0-9._-]{2,}@[a-z][a-z0-9.-]+\b", "VPA-shaped"),
            (r"\b\d{9,18}\b", "account-number-shaped"),
        )
        for pattern, label in patterns:
            if re.search(pattern, text):
                return label
        return None


def build_model_context(decision: DecisionObject, lang: str = "en") -> dict:
    """The *only* thing the model is given.

    Tokenised references and pre-rendered amounts — no narrations, no names, no
    account identifiers, no raw features. If this dictionary leaked in full it
    would identify nobody, which is the design goal of report §7.7's fourth
    bullet.

    Note that the model receives the decision as *already made*. There is no
    field here it could alter to change an outcome; it is being asked to phrase
    a conclusion, not to reach one.
    """
    rendering = decision.render_customer(lang)
    context: dict = {
        "task": "Render the completed decision below as one natural sentence in the target language.",
        "constraints": [
            "Do not introduce any number that is not in allowed_numbers.",
            "Do not promise approval, create urgency, or request any credential.",
            "Do not add advice, alternatives or products beyond what is stated.",
        ],
        "target_language": lang,
        "outcome": decision.outcome.value,
        "headline": rendering.headline,
        "detail": rendering.detail,
        "counterfactual": rendering.counterfactual,
        "allowed_numbers": list(rendering.allowed_numbers),
        "rendered_amounts": {},
    }
    if decision.offer:
        from ..core.money import format_inr

        context["rendered_amounts"] = {
            "amount": format_inr(decision.offer.amount_paise),
            "emi": format_inr(decision.offer.emi_paise),
            "tenure_months": decision.offer.tenure_months,
            "total_interest": format_inr(decision.offer.total_interest_paise),
        }
        context["product_name"] = decision.offer.product.name
    return context
