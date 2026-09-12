"""ARTHA orchestrator — the decision pipeline, end to end.

This is the module the API calls and the one that defines the system's actual
order of operations. Report Figure 2: transaction event → moment → affordability
→ gate → delivered action, with **silence and rejection as valid outcomes**.

The ordering below is itself a safety property, so it is stated explicitly:

  1. **Sentinel first.** Before considering whether to sell anything, establish
     whether the customer is being defrauded or is in distress. A system that
     ranks products first and checks for stress afterwards will, on some
     unlucky day, offer a loan to someone mid-scam.
  2. **Moment, then structure, then simulate.** The Twin runs on a concrete
     structure, because affordability is a property of a specific EMI on a
     specific date, not of a product category.
  3. **Gate last, and able to override everything above it.**
  4. **Counterfactual on refusal.** A refusal without one is a failure of this
     pipeline, not an acceptable outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .audit.log import DEFAULT_LOG, AuditLog, RecordType
from .consent.manager import DEFAULT_MANAGER, ConsentManager, build_ledger_entry
from .consent.purposes import Purpose
from .core import reason_codes as rc
from .core.decision import (
    CounterfactualSummary,
    DecisionObject,
    GateCheck,
    MomentEvidence,
    ReasonEntry,
    TwinSummary,
)
from .core.money import format_inr
from .core.types import (
    CustomerProfile,
    EnrichedTransaction,
    GateOutcome,
    IncomeType,
    PayIntent,
    RecoveryState,
    SentinelVerdict,
    Transaction,
)
from .engines.moment import DEFAULT_ENGINE as MOMENT_ENGINE
from .engines.moment import Moment, MomentEngine
from .engines.profitability import ProfitabilityEngine
from .engines.sentinel import Sentinel, SentinelResult
from .engines.twin import FinancialTwin, Obligation, TwinResult, TwinVerdict
from .features.builder import build_profile, write_features
from .features.store import FeatureStore
from .gate.conduct import DEFAULT_BUDGET, DEFAULT_CALENDAR, EmpathyCalendar, NudgeBudget
from .gate.fairness import DEFAULT_MONITOR, FairnessMonitor
from .gate.recovery import DEFAULT_MACHINE, RecoveryMachine
from .gate.suitability_gate import GateDecision, SuitabilityGate
from .intervention.ladder import DEFAULT_LADDER, InterventionLadder, LadderResult
from .ontology.enrich import DEFAULT_PIPELINE, EnrichmentPipeline, EnrichmentResult
from .products.catalogue import BY_ID, ProductOffer

MODEL_VERSIONS = {
    "ontology": "0.1.0",
    "income_type": "0.1.0",
    "twin": "0.1.0",
    "ranker": "0.1.0-rules",
    "sentinel": "0.1.0",
    "policy": "0.1.0",
}


@dataclass
class CustomerState:
    """Everything the orchestrator holds about one customer between calls."""

    customer_token: str
    profile: CustomerProfile
    enrichment: EnrichmentResult
    transactions: list[Transaction] = field(default_factory=list)
    gender: str | None = None

    @property
    def enriched(self) -> list[EnrichedTransaction]:
        return self.enrichment.enriched


@dataclass(frozen=True)
class DecisionBundle:
    """A decision plus everything the surfaces need to render it."""

    decision: DecisionObject
    gate: GateDecision
    sentinel: SentinelResult | None = None
    ladder: LadderResult | None = None
    moments: tuple[Moment, ...] = field(default_factory=tuple)
    privacy_ledger: dict = field(default_factory=dict)
    suppressed_candidates: tuple[dict, ...] = field(default_factory=tuple)


class ArthaEngine:
    """Wires the components together. One instance per process."""

    def __init__(
        self,
        *,
        pipeline: EnrichmentPipeline | None = None,
        twin: FinancialTwin | None = None,
        moment: MomentEngine | None = None,
        sentinel: Sentinel | None = None,
        ladder: InterventionLadder | None = None,
        recovery: RecoveryMachine | None = None,
        budget: NudgeBudget | None = None,
        calendar: EmpathyCalendar | None = None,
        fairness: FairnessMonitor | None = None,
        consent: ConsentManager | None = None,
        audit: AuditLog | None = None,
        features: FeatureStore | None = None,
    ) -> None:
        # `x if x is not None else DEFAULT` rather than `x or DEFAULT`.
        #
        # This is not style. `AuditLog` defines `__len__`, so a freshly injected
        # *empty* log is falsy and `audit or DEFAULT_LOG` silently discards it in
        # favour of the module-level singleton — the caller believes they have an
        # isolated log and are in fact writing to a shared one. Any collaborator
        # that grows a `__len__` or `__bool__` later would acquire the same bug,
        # so the explicit form is used for all of them.
        self.pipeline = pipeline if pipeline is not None else DEFAULT_PIPELINE
        self.twin = twin if twin is not None else FinancialTwin()
        self.moment = moment if moment is not None else MOMENT_ENGINE
        self.sentinel = sentinel if sentinel is not None else Sentinel()
        self.ladder = ladder if ladder is not None else DEFAULT_LADDER
        self.recovery = recovery if recovery is not None else DEFAULT_MACHINE
        self.budget = budget if budget is not None else DEFAULT_BUDGET
        self.calendar = calendar if calendar is not None else DEFAULT_CALENDAR
        self.fairness = fairness if fairness is not None else DEFAULT_MONITOR
        self.consent = consent if consent is not None else DEFAULT_MANAGER
        self.audit = audit if audit is not None else DEFAULT_LOG
        self.features = features if features is not None else FeatureStore()
        self.profitability = ProfitabilityEngine(twin=self.twin)
        self.gate = SuitabilityGate(
            recovery=self.recovery, budget=self.budget, calendar=self.calendar,
            fairness=self.fairness, consent=self.consent,
        )
        self._states: dict[str, CustomerState] = {}

    # ---------------------------------------------------------------- ingest

    def ingest(
        self,
        customer_token: str,
        transactions: list[Transaction],
        *,
        balance_paise: int | None = None,
        income_override: IncomeType | None = None,
        as_of: date | None = None,
        **profile_kwargs,
    ) -> CustomerState:
        """Enrich a transaction history and build the consent-scoped profile."""
        as_of = as_of or date.today()

        # Gender is a fairness *slice*, never a profile feature. It is taken off
        # here so it cannot reach the profile the engines see — report §7.3 and
        # §9.5 require that slice attributes measure outcomes without being
        # available to decide them, and the cleanest enforcement is that the
        # value is not in the object at all.
        gender = profile_kwargs.pop("gender", None)

        enrichment = self.pipeline.run(
            transactions, income_override=income_override, as_of=as_of
        )

        if balance_paise is None:
            with_balance = [t for t in transactions if t.balance_after_paise is not None]
            balance_paise = (
                max(with_balance, key=lambda t: t.ts).balance_after_paise
                if with_balance else 0
            )

        profile = build_profile(
            customer_token, enrichment, balance_paise=balance_paise, as_of=as_of,
            **profile_kwargs,
        )

        # Narrations carrying injection payloads are logged as a security event
        # the moment they are seen. They changed nothing — the parser emits typed
        # values regardless — but an attempt that is never recorded is an attempt
        # nobody can count.
        if enrichment.injection_findings:
            self.audit.append(
                RecordType.INJECTION_DETECTED, customer_token,
                {
                    "count": len(enrichment.injection_findings),
                    "patterns": sorted({f.pattern for _, f in enrichment.injection_findings}),
                    "txn_ids": [t for t, _ in enrichment.injection_findings][:20],
                    "note": (
                        "Narrations are parsed to typed values and never reach the "
                        "language model; these had no path to influence a decision."
                    ),
                },
            )

        # Publish into the consent-scoped feature store. Engines read the
        # profile, but the store is what makes revocation observable: it can
        # report exactly which features would be withheld at inference time.
        write_features(self.features, customer_token, profile, as_of=as_of)

        state = CustomerState(
            customer_token=customer_token, profile=profile,
            enrichment=enrichment, transactions=list(transactions),
            gender=gender,
        )
        self._states[customer_token] = state
        return state

    def state(self, customer_token: str) -> CustomerState:
        if customer_token not in self._states:
            raise KeyError(f"no ingested state for {customer_token}")
        return self._states[customer_token]

    # ---------------------------------------------------------------- decide

    def decide(
        self,
        customer_token: str,
        *,
        as_of: date | None = None,
        requested_product_id: str | None = None,
        requested_amount_paise: int | None = None,
        missed_payment: bool = False,
        language: str | None = None,
    ) -> DecisionBundle:
        as_of = as_of or date.today()
        st = self.state(customer_token)
        profile = st.profile
        lang = language or profile.language

        # -- 1. Sentinel, before anything is considered for sale -------------
        baseline_twin = self.twin.simulate(profile, None, as_of=as_of)
        sentinel = self.sentinel.assess(
            profile, st.enriched, as_of=as_of,
            twin_resilience=baseline_twin.resilience_score,
            missed_payment=missed_payment,
        )
        self._log_stress_unconditionally(customer_token, sentinel)

        if sentinel.is_fraud:
            return self._fraud_bundle(st, sentinel, lang, as_of)

        if sentinel.is_distress and sentinel.pay_intent is not PayIntent.UNWILLING:
            self._enter_recovery(customer_token, sentinel, as_of)
            return self._assistance_bundle(st, sentinel, baseline_twin, lang, as_of)

        # -- 2. Moments -------------------------------------------------------
        moments = self.moment.detect(profile, st.enriched, as_of=as_of)
        if not moments:
            return self._silence_bundle(st, sentinel, lang, as_of, moments=())

        # -- 3/4. Structure, simulate, gate each candidate --------------------
        suppressed: list[dict] = []
        for moment in moments:
            product_ids = (
                (requested_product_id,) if requested_product_id else moment.product_ids
            )
            for product_id in product_ids:
                product = BY_ID.get(product_id)
                if product is None:
                    continue

                offer = self.profitability.structure(
                    profile, product,
                    requested_amount_paise=requested_amount_paise, as_of=as_of,
                )
                if offer is None:
                    suppressed.append(self._suppressed_note(
                        product_id, "No structure at any tenure keeps the balance above the buffer."
                    ))
                    continue

                twin = self.twin.simulate(
                    profile,
                    Obligation(
                        label=product.name, emi_paise=offer.emi_paise,
                        day_of_month=offer.day_of_month, tenure_months=offer.tenure_months,
                        principal_paise=offer.amount_paise, annual_rate=offer.annual_rate,
                    ),
                    as_of=as_of,
                )
                gate = self.gate.evaluate(
                    profile, offer, twin=twin, as_of=as_of, gender=st.gender
                )

                if gate.outcome is GateOutcome.ACT:
                    return self._act_bundle(st, offer, twin, gate, moment, sentinel, lang, as_of)

                suppressed.append(self._suppressed_note(
                    product_id, gate.trace[-1].detail if gate.trace else "",
                    blocking=gate.blocking_check,
                ))

        # Everything was suppressed. Produce a counterfactual for the best
        # candidate so the customer receives a structure, not a refusal.
        return self._counterfactual_bundle(
            st, moments, sentinel, lang, as_of, suppressed
        )

    # ------------------------------------------------------------- outcomes

    def _act_bundle(
        self, st, offer, twin, gate, moment, sentinel, lang, as_of
    ) -> DecisionBundle:
        decision = self._build_decision(
            st, GateOutcome.ACT, gate, lang, as_of,
            offer=offer, twin=twin, moment=moment,
        )
        self.budget.record_contact(st.customer_token, offer.product.family.value, as_of)
        self.fairness.record(st.profile, GateOutcome.ACT, gender=st.gender)
        self._log_decision(decision)
        return DecisionBundle(
            decision=decision, gate=gate, sentinel=sentinel,
            moments=(moment,), privacy_ledger=self._ledger(decision, gate, lang, as_of),
        )

    def _counterfactual_bundle(
        self, st, moments, sentinel, lang, as_of, suppressed
    ) -> DecisionBundle:
        profile = st.profile
        moment = moments[0]
        product = BY_ID.get(moment.product_ids[0]) if moment.product_ids else None

        counterfactual = None
        twin = None
        if product is not None and product.annual_rate > 0:
            requested = Obligation(
                label=product.name, emi_paise=0,
                day_of_month=self.profitability.repayment_day(profile),
                tenure_months=max(product.tenures),
                principal_paise=self.profitability.maximum_eligible_paise(profile, product),
                annual_rate=product.annual_rate,
            )
            counterfactual = self.twin.counterfactual(profile, requested, as_of=as_of)
            twin = self.twin.simulate(profile, None, as_of=as_of)

        gate = self.gate.evaluate(profile, None, twin=None, as_of=as_of, gender=st.gender)
        reasons = list(gate.reasons)
        if counterfactual is not None and counterfactual.available:
            reasons.append(ReasonEntry(
                rc.CFA_AVAILABLE.code, weight=1.0,
                params={
                    "amount": format_inr(counterfactual.amount_paise),
                    "tenure": str(counterfactual.tenure_months),
                    "emi": format_inr(counterfactual.emi_paise),
                },
            ))
        elif not reasons:
            reasons.append(ReasonEntry(rc.MOM_NO_TRIGGER.code, weight=0.5))

        decision = self._build_decision(
            st, GateOutcome.SUPPRESS, gate, lang, as_of,
            twin=twin, moment=moment, reasons=reasons,
            counterfactual=counterfactual,
        )
        self.fairness.record(profile, GateOutcome.SUPPRESS, gender=st.gender)
        self._log_decision(decision)
        return DecisionBundle(
            decision=decision, gate=gate, sentinel=sentinel, moments=tuple(moments),
            privacy_ledger=self._ledger(decision, gate, lang, as_of),
            suppressed_candidates=tuple(suppressed),
        )

    def _silence_bundle(self, st, sentinel, lang, as_of, moments) -> DecisionBundle:
        """Silence is an explicit, valid output (report §6.1)."""
        gate = self.gate.evaluate(st.profile, None, twin=None, as_of=as_of, gender=st.gender)
        decision = self._build_decision(
            st, GateOutcome.SUPPRESS, gate, lang, as_of,
            reasons=[ReasonEntry(rc.MOM_NO_TRIGGER.code, weight=1.0)],
        )
        self.fairness.record(st.profile, GateOutcome.SUPPRESS, gender=st.gender)
        self._log_decision(decision)
        return DecisionBundle(
            decision=decision, gate=gate, sentinel=sentinel, moments=moments,
            privacy_ledger=self._ledger(decision, gate, lang, as_of),
        )

    def _fraud_bundle(self, st, sentinel, lang, as_of) -> DecisionBundle:
        worst = sentinel.fraud_signals[0]
        gate = self.gate.evaluate(
            st.profile, None, twin=None, as_of=as_of, gender=st.gender, is_assistance=True
        )
        decision = self._build_decision(
            st, GateOutcome.VERIFY, gate, lang, as_of,
            reasons=[ReasonEntry(
                rc.SEN_FRAUD_HOLD.code, weight=1.0,
                params={"minutes": str(worst.cooling_off_minutes or 30)},
            )],
        )
        self.audit.append(
            RecordType.FRAUD_HOLD, st.customer_token,
            {
                "decision_id": decision.decision_id,
                "patterns": [f.pattern for f in sentinel.fraud_signals],
                "responses": [f.response for f in sentinel.fraud_signals],
                "evidence": [list(f.evidence) for f in sentinel.fraud_signals],
            },
        )
        self._log_decision(decision)
        return DecisionBundle(
            decision=decision, gate=gate, sentinel=sentinel,
            privacy_ledger=self._ledger(decision, gate, lang, as_of),
        )

    def _assistance_bundle(self, st, sentinel, baseline_twin, lang, as_of) -> DecisionBundle:
        """Distress detected: assist, never sell."""
        profile = st.profile
        emi_series = [
            s for s in profile.series
            if s.direction.value == "DEBIT" and s.category.value == "EMI" and s.day_of_month
        ]
        ladder: LadderResult | None = None
        if emi_series:
            s = emi_series[0]
            ladder = self.ladder.build(
                profile,
                current_emi_paise=s.median_amount_paise,
                current_day_of_month=s.day_of_month or 5,
                remaining_tenure_months=24,
                annual_rate=0.145,
                outstanding_paise=s.median_amount_paise * 24,
                pay_intent=sentinel.pay_intent,
                as_of=as_of,
            )

        gate = self.gate.evaluate(
            profile, None, twin=None, as_of=as_of, gender=st.gender, is_assistance=True
        )
        reasons = [ReasonEntry(
            rc.SEN_STRESS_PREDICTED.code, weight=1.0,
            params={"days": str(sentinel.lead_time_days or 0)},
        )]
        if ladder and ladder.recommended:
            reasons.append(ReasonEntry(
                ladder.recommended.reason_code, weight=0.95,
                params=dict(ladder.recommended.reason_params),
            ))

        decision = self._build_decision(
            st, GateOutcome.PROTECT, gate, lang, as_of,
            twin=baseline_twin, reasons=reasons,
        )

        if ladder and ladder.recommended:
            self.audit.append(
                RecordType.INTERVENTION_OFFERED, st.customer_token,
                {
                    "decision_id": decision.decision_id,
                    "rung": int(ladder.recommended.rung),
                    "name": ladder.recommended.name,
                    "regulatory_cost": ladder.recommended.regulatory_cost,
                    "economic_cost_paise": ladder.recommended.economic_cost_paise,
                    "alternatives_considered": [a.name for a in ladder.alternatives],
                    "note": (
                        "Logged separately from the stress observation: detection is "
                        "unconditional, the decision to assist is a distinct step "
                        "(report §9.4)."
                    ),
                },
            )

        self.fairness.record(profile, GateOutcome.PROTECT, gender=st.gender)
        self._log_decision(decision)
        return DecisionBundle(
            decision=decision, gate=gate, sentinel=sentinel, ladder=ladder,
            privacy_ledger=self._ledger(decision, gate, lang, as_of),
        )

    # -------------------------------------------------------------- helpers

    def _build_decision(
        self, st, outcome, gate, lang, as_of, *,
        offer: ProductOffer | None = None,
        twin: TwinResult | None = None,
        moment: Moment | None = None,
        reasons: list[ReasonEntry] | None = None,
        counterfactual=None,
    ) -> DecisionObject:
        record = self.recovery.get(st.customer_token)
        scoped = self.features.scoped_view(st.customer_token, self.consent, as_of=as_of)
        all_reasons = list(reasons if reasons is not None else gate.reasons)
        if moment is not None and not any(r.code == moment.reason_code for r in all_reasons):
            all_reasons.insert(0, ReasonEntry(
                moment.reason_code, weight=0.99, params=dict(moment.reason_params)
            ))

        return DecisionObject(
            decision_id=DecisionObject.new_id(),
            customer_token=st.customer_token,
            created_at=DecisionObject.now(),
            outcome=outcome,
            offer=offer,
            moment=(
                MomentEvidence(
                    trigger=moment.trigger, description=moment.description,
                    evidence_dates=moment.evidence_dates, series_id=moment.series_id,
                ) if moment else None
            ),
            twin=_summarise_twin(twin) if twin else None,
            counterfactual=(
                CounterfactualSummary(
                    available=counterfactual.available,
                    amount_paise=counterfactual.amount_paise,
                    tenure_months=counterfactual.tenure_months,
                    emi_paise=counterfactual.emi_paise,
                    blocker=counterfactual.blocker,
                ) if counterfactual else None
            ),
            gate_trace=gate.trace,
            reasons=tuple(all_reasons),
            recovery_state=record.state,
            language=lang,
            model_versions=dict(MODEL_VERSIONS),
            consent_purposes_used=tuple(p.value for p in gate.purposes_used),
            consent_purposes_excluded=tuple(
                sorted(p.value for p in self.consent.excluded_purposes(
                    st.customer_token, as_of=as_of
                ))
            ),
            features_excluded=scoped.excluded_names,
            input_hash=DecisionObject.hash_inputs({
                "customer": st.customer_token,
                "as_of": as_of.isoformat(),
                "txn_count": len(st.transactions),
                "balance": st.profile.balance_paise,
                "income_type": st.profile.income_type.value,
            }),
        )

    def _log_stress_unconditionally(self, customer_token: str, sentinel: SentinelResult) -> None:
        """Report §9.4: the Sentinel reports stress whether or not assistance follows."""
        if sentinel.verdict is SentinelVerdict.NORMAL:
            return
        self.audit.append(
            RecordType.STRESS_OBSERVATION, customer_token,
            {
                "verdict": sentinel.verdict.value,
                "pd_uplift_90d": sentinel.pd_uplift_90d,
                "anomaly_score": sentinel.anomaly_score,
                "pay_intent": sentinel.pay_intent.value,
                "lead_time_days": sentinel.lead_time_days,
                "evidence": list(sentinel.evidence),
                "note": (
                    "Reported to the risk function unconditionally. Whether an "
                    "intervention follows is a separate, separately logged decision."
                ),
            },
        )

    def _enter_recovery(self, customer_token: str, sentinel: SentinelResult, as_of: date) -> None:
        target = (
            RecoveryState.AT_RISK if sentinel.pd_uplift_90d >= 0.05 else RecoveryState.WATCH
        )
        record = self.recovery.get(customer_token)
        if record.state is target:
            return
        self.recovery.transition(
            customer_token, target,
            reason=f"Sentinel PD uplift +{sentinel.pd_uplift_90d:.1%} over 90 days",
            evidence=tuple(sentinel.evidence), at=as_of,
        )
        self.audit.append(
            RecordType.RECOVERY_TRANSITION, customer_token,
            {"to_state": target.value, "evidence": list(sentinel.evidence)},
        )

    def _log_decision(self, decision: DecisionObject) -> None:
        self.audit.append(
            RecordType.DECISION, decision.customer_token, decision.render_regulator()
        )

    def _ledger(self, decision, gate, lang, as_of) -> dict:
        entry = build_ledger_entry(
            self.consent,
            decision_id=decision.decision_id,
            customer_token=decision.customer_token,
            purposes_used=set(gate.purposes_used),
            as_of=as_of, lang=lang,
        )
        return entry.render(lang)

    @staticmethod
    def _suppressed_note(product_id: str, detail: str, blocking: str | None = None) -> dict:
        """Feeds the 'what we are not offering, and why' panel of report §6.6,
        and the product-design feedback loop of §8.1."""
        return {"product_id": product_id, "reason": detail, "blocking_check": blocking}


def _summarise_twin(twin: TwinResult) -> TwinSummary:
    return TwinSummary(
        verdict=twin.verdict.value,
        safe_buffer_paise=twin.safe_buffer_paise,
        min_balance_p05_paise=twin.min_balance_p05_paise,
        breach_probability=twin.breach_probability,
        baseline_breach_probability=twin.baseline_breach_probability,
        resilience_score=twin.resilience_score,
        shocks_absorbed=twin.shocks_absorbed,
        first_breach_date=twin.first_breach_date.isoformat() if twin.first_breach_date else None,
        sentence_en=twin.sentence_en,
        scenarios=tuple(
            {
                "key": s.key, "label": s.label, "passed": s.passed,
                "breach_probability": s.breach_probability,
                "min_balance_p05_paise": s.min_balance_p05_paise,
            }
            for s in twin.scenarios
        ),
        path_with=twin.median_path_with,
        path_without=twin.median_path_without,
        path_p05=twin.p05_path_with,
    )
