"""The Decision Object — one artefact, rendered twice.

Report §7.6 and §12. This is the structural answer to explainability: the
regulator-grade trace and the single spoken sentence are produced from the same
object, so what the auditor is told and what the customer is told cannot drift
apart. Two renderers, one source of truth — not two pipelines that are supposed
to agree.

The object also defines the *numeric ground truth* for the AI Firewall. Every
numeral the language model is permitted to utter must appear in
:meth:`DecisionObject.numeric_ground`. Anything else blocks the response
(§7.7). This is why the renderers live next to the data rather than in the
presentation layer: the permitted numbers and the sentence that uses them have
to come from the same place, or the check is checking nothing.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..products.catalogue import ProductOffer
from . import reason_codes as rc
from .money import format_inr, spoken_inr
from .types import GateOutcome, ProductFamily, RecoveryState


@dataclass(frozen=True)
class GateCheck:
    """One constraint, its verdict, and why.

    The full sequence of these is the "gate trace" of report §6.7 — every
    constraint and its outcome, including the ones that passed. A trace that
    records only the failing check cannot demonstrate that the others ran.
    """

    name: str
    passed: bool
    detail: str
    reason_code: str | None = None
    outcome_if_failed: GateOutcome = GateOutcome.SUPPRESS


@dataclass(frozen=True)
class ReasonEntry:
    code: str
    weight: float = 0.0                       # SHAP contribution, or rule weight
    params: dict[str, str] = field(default_factory=dict)

    @property
    def spec(self) -> rc.ReasonCodeSpec:
        return rc.get(self.code)

    def say(self, lang: str = "en") -> str:
        return self.spec.say(lang, **self.params)


@dataclass(frozen=True)
class MomentEvidence:
    """What changed, and when. Report §7.6 requires the triggering evidence to
    carry dates — an assertion that "an EMI is ending" is not auditable without
    the series and the date it ends."""

    trigger: str
    description: str
    evidence_dates: tuple[str, ...] = field(default_factory=tuple)
    series_id: str | None = None


@dataclass(frozen=True)
class TwinSummary:
    """Flattened Twin output for transport and persistence."""

    verdict: str
    safe_buffer_paise: int
    min_balance_p05_paise: int
    breach_probability: float
    baseline_breach_probability: float
    resilience_score: float
    shocks_absorbed: int
    first_breach_date: str | None
    sentence_en: str
    scenarios: tuple[dict, ...] = field(default_factory=tuple)
    path_with: tuple[int, ...] = field(default_factory=tuple)
    path_without: tuple[int, ...] = field(default_factory=tuple)
    path_p05: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CounterfactualSummary:
    available: bool
    amount_paise: int = 0
    tenure_months: int = 0
    emi_paise: int = 0
    blocker: str = ""


@dataclass(frozen=True)
class CustomerRendering:
    """What the customer hears. One sentence, plus the numbers behind it.

    ``allowed_numbers`` travels with the rendering because the firewall check
    happens after the language model has phrased it, and the check needs to know
    what was legitimately available to say.
    """

    language: str
    headline: str
    detail: str
    counterfactual: str | None
    spoken: str
    allowed_numbers: tuple[float, ...]
    privacy_note: str


@dataclass(frozen=True)
class DecisionObject:
    """The single source of truth for one decision about one customer."""

    decision_id: str
    customer_token: str
    created_at: str
    outcome: GateOutcome

    offer: ProductOffer | None = None
    moment: MomentEvidence | None = None
    twin: TwinSummary | None = None
    counterfactual: CounterfactualSummary | None = None

    gate_trace: tuple[GateCheck, ...] = field(default_factory=tuple)
    reasons: tuple[ReasonEntry, ...] = field(default_factory=tuple)
    shap: dict[str, float] = field(default_factory=dict)

    recovery_state: RecoveryState = RecoveryState.STABLE
    language: str = "hi"
    channel: str = "APP"

    model_versions: dict[str, str] = field(default_factory=dict)
    policy_version: str = "0.1.0"
    consent_purposes_used: tuple[str, ...] = field(default_factory=tuple)
    consent_purposes_excluded: tuple[str, ...] = field(default_factory=tuple)
    features_excluded: tuple[str, ...] = field(default_factory=tuple)
    input_hash: str = ""

    # ---------------------------------------------------------------- build

    @staticmethod
    def new_id() -> str:
        return f"dec_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    @staticmethod
    def hash_inputs(payload: dict) -> str:
        """Stable hash of the decision inputs.

        Written into the audit log so a supervisor can confirm that a re-run
        used the same inputs, which is the only way a reproducibility claim
        means anything.
        """
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()

    # ------------------------------------------------------- renderings

    def render_regulator(self) -> dict:
        """The supervisory rendering: decision, evidence, trace, attribution.

        Deliberately verbose. This is the artefact an evidence pack is built
        from (report §6.7), and the cost of an extra field here is nothing
        against the cost of a decision that cannot be reconstructed.
        """
        return {
            "decision_id": self.decision_id,
            "customer_token": self.customer_token,
            "created_at": self.created_at,
            "outcome": self.outcome.value,
            "policy_version": self.policy_version,
            "model_versions": dict(self.model_versions),
            "input_hash": self.input_hash,
            "recovery_state": self.recovery_state.value,
            "moment": (
                {
                    "trigger": self.moment.trigger,
                    "description": self.moment.description,
                    "evidence_dates": list(self.moment.evidence_dates),
                    "series_id": self.moment.series_id,
                }
                if self.moment else None
            ),
            "offer": (
                {
                    "product_id": self.offer.product.product_id,
                    "product_name": self.offer.product.name,
                    "family": self.offer.product.family.value,
                    "amount_paise": self.offer.amount_paise,
                    "eligible_amount_paise": self.offer.eligible_amount_paise,
                    "reduced_from_eligibility": self.offer.is_reduced_from_eligibility,
                    "tenure_months": self.offer.tenure_months,
                    "emi_paise": self.offer.emi_paise,
                    "day_of_month": self.offer.day_of_month,
                    "annual_rate": self.offer.annual_rate,
                    "total_interest_paise": self.offer.total_interest_paise,
                }
                if self.offer else None
            ),
            "twin": (
                {
                    "verdict": self.twin.verdict,
                    "safe_buffer_paise": self.twin.safe_buffer_paise,
                    "min_balance_p05_paise": self.twin.min_balance_p05_paise,
                    "breach_probability": self.twin.breach_probability,
                    "baseline_breach_probability": self.twin.baseline_breach_probability,
                    "resilience_score": self.twin.resilience_score,
                    "shocks_absorbed": self.twin.shocks_absorbed,
                    "first_breach_date": self.twin.first_breach_date,
                    "scenarios": [dict(s) for s in self.twin.scenarios],
                }
                if self.twin else None
            ),
            "counterfactual": (
                {
                    "available": self.counterfactual.available,
                    "amount_paise": self.counterfactual.amount_paise,
                    "tenure_months": self.counterfactual.tenure_months,
                    "emi_paise": self.counterfactual.emi_paise,
                    "blocker": self.counterfactual.blocker,
                }
                if self.counterfactual else None
            ),
            "gate_trace": [
                {
                    "check": c.name,
                    "passed": c.passed,
                    "detail": c.detail,
                    "reason_code": c.reason_code,
                    "outcome_if_failed": c.outcome_if_failed.value,
                }
                for c in self.gate_trace
            ],
            "reason_codes": [
                {
                    "code": r.code,
                    "title": r.spec.title,
                    "description": r.spec.description,
                    "polarity": r.spec.polarity.value,
                    "adverse_action": r.spec.adverse_action,
                    "weight": r.weight,
                    "params": dict(r.params),
                }
                for r in self.reasons
            ],
            "shap": dict(self.shap),
            "consent": {
                "purposes_used": list(self.consent_purposes_used),
                "purposes_excluded": list(self.consent_purposes_excluded),
                "features_excluded_at_inference": list(self.features_excluded),
            },
        }

    def render_customer(self, lang: str | None = None) -> CustomerRendering:
        """The customer rendering: one sentence, in their language.

        Built from the same reason codes the regulator rendering cites, taking
        the highest-weighted reason as the headline. Where the two renderings
        differ is only in register, never in substance.
        """
        lang = lang or self.language
        ranked = sorted(self.reasons, key=lambda r: -abs(r.weight))
        headline = ranked[0].say(lang) if ranked else ""

        detail_parts = [r.say(lang) for r in ranked[1:3]]
        detail = " ".join(p for p in detail_parts if p)

        counterfactual_text = None
        if self.counterfactual and self.counterfactual.available:
            counterfactual_text = rc.CFA_AVAILABLE.say(
                lang,
                amount=format_inr(self.counterfactual.amount_paise),
                tenure=self.counterfactual.tenure_months,
                emi=format_inr(self.counterfactual.emi_paise),
            )

        spoken = self._spoken(lang, headline, detail, counterfactual_text)

        return CustomerRendering(
            language=lang,
            headline=headline,
            detail=detail,
            counterfactual=counterfactual_text,
            spoken=spoken,
            allowed_numbers=self.numeric_ground(),
            privacy_note=self._privacy_note(lang),
        )

    def _spoken(self, lang: str, headline: str, detail: str, cf: str | None) -> str:
        parts = [headline]
        if detail:
            parts.append(detail)
        if cf:
            parts.append(cf)
        if self.offer:
            parts.append(
                rc.PRF_TWIN_SAFE_EXPOSURE.say(
                    lang,
                    eligible=spoken_inr(self.offer.eligible_amount_paise, lang).phrase,
                    recommended=spoken_inr(self.offer.amount_paise, lang).phrase,
                )
                if self.offer.is_reduced_from_eligibility else ""
            )
        return " ".join(p for p in parts if p).strip()

    def _privacy_note(self, lang: str) -> str:
        """The privacy-ledger line that accompanies every nudge (report §6.6).

        Names what was used and what was explicitly not. Where the feature store
        actually withheld something at inference time, that is named too — a
        withheld feature is the strongest form of the claim, because it is a
        thing the engines could not see rather than a thing they chose not to
        look at.
        """
        used = ", ".join(self.consent_purposes_used) or "none"
        excluded = ", ".join(self.consent_purposes_excluded) or "none"
        withheld = ", ".join(self.features_excluded)
        if lang == "hi":
            note = f"उपयोग किया गया डेटा: {used}। उपयोग नहीं किया गया: {excluded}।"
            if withheld:
                note += f" आपकी अनुमति न होने के कारण रोका गया: {withheld}।"
            return note
        note = f"Data used: {used}. Data explicitly not used: {excluded}."
        if withheld:
            note += f" Withheld at inference because you did not permit it: {withheld}."
        return note

    # ------------------------------------------------------ firewall ground

    def numeric_ground(self) -> tuple[float, ...]:
        """Every number the language model is allowed to say.

        Report §7.7: any numeral in model output that does not match a field in
        the Decision Object blocks the response and falls back to a template.
        This mechanically eliminates hallucinated rates and fees — the most
        dangerous failure mode in regulated lending — so the completeness of
        this list is a safety property, not a convenience.
        """
        values: list[float] = []

        def money(*paise_values) -> None:
            """Money enters the ground in **rupees**, never paise.

            The model is only ever handed pre-rendered amounts (report §7.7), so
            a paise figure is something it could only have invented. Admitting
            both forms also widens the ground enormously: with ₹10,000 present as
            1,000,000 paise, a hallucinated "999999" lands within tolerance of a
            legitimate value and passes a check that exists to catch exactly that.
            """
            for p in paise_values:
                if p is None:
                    continue
                values.append(float(round(float(p) / 100.0)))

        def scalar(*nums) -> None:
            for n in nums:
                if n is not None:
                    values.append(float(n))

        if self.offer:
            money(
                self.offer.amount_paise,
                self.offer.eligible_amount_paise,
                self.offer.emi_paise,
                self.offer.total_interest_paise,
                self.offer.emi_paise * self.offer.tenure_months,   # total repayable
            )
            scalar(
                self.offer.tenure_months,
                self.offer.day_of_month,
                round(self.offer.annual_rate * 100, 2),
            )
        if self.twin:
            money(self.twin.safe_buffer_paise, self.twin.min_balance_p05_paise)
            scalar(
                self.twin.resilience_score,
                self.twin.shocks_absorbed,
                round(self.twin.breach_probability * 100, 1),
            )
        if self.counterfactual and self.counterfactual.available:
            money(self.counterfactual.amount_paise, self.counterfactual.emi_paise)
            scalar(self.counterfactual.tenure_months)

        # Reason-code parameters are already rendered for a human ("₹1,00,000"),
        # so the numerals extracted from them are rupee-scale by construction.
        for r in self.reasons:
            for v in r.params.values():
                scalar(*_numbers_in(str(v)))

        return tuple(sorted(set(values)))

    @property
    def is_adverse_action(self) -> bool:
        """Whether this decision requires human review before it stands.

        Report §9.6: human review is required for adverse actions. The property
        is derived from the reason codes rather than set by a caller, so a new
        adverse reason cannot be introduced without inheriting the review
        requirement.
        """
        return any(r.spec.adverse_action for r in self.reasons)

    @property
    def product_family(self) -> ProductFamily | None:
        return self.offer.product.family if self.offer else None


def _numbers_in(text: str) -> list[float]:
    import re

    out: list[float] = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return out
