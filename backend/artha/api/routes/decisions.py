"""Decision endpoints — ingest, decide, explain, render."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException

from ...audit.log import RecordType
from ...core.decision import DecisionObject
from ...core.money import format_inr
from ...core.types import IncomeType
from ...language.kfs import build_kfs
from ...llm.capability import Capability
from ...llm.firewall import build_model_context
from ...schemas.api import (
    DecideRequest,
    IngestRequest,
    RenderRequest,
    SeedRequest,
)
from ...synth.generator import ARCHETYPES, SyntheticGenerator
from ..deps import DEMO_AS_OF, get_broker, get_engine, get_firewall, parse_transactions

router = APIRouter(tags=["decisions"])


@router.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    engine = get_engine()
    as_of = req.as_of or DEMO_AS_OF
    engine.consent.grant_defaults(req.customer_token, as_of=as_of)

    override = None
    if req.income_type_override:
        try:
            override = IncomeType(req.income_type_override)
        except ValueError as exc:
            raise HTTPException(400, f"unknown income type: {req.income_type_override}") from exc

    state = engine.ingest(
        req.customer_token,
        parse_transactions(req.customer_token, req.transactions),
        balance_paise=req.balance_paise,
        income_override=override,
        as_of=as_of,
        language=req.language,
        age=req.age, dependants=req.dependants, thin_file=req.thin_file,
        district=req.district, is_rural=req.is_rural, gender=req.gender,
        tenure_with_bank_months=req.tenure_with_bank_months,
        on_time_emi_streak=req.on_time_emi_streak,
        credit_utilisation=req.credit_utilisation,
        has_term_cover=req.has_term_cover, has_health_cover=req.has_health_cover,
    )
    return _profile_payload(state)


@router.post("/seed")
def seed(req: SeedRequest) -> dict:
    """Ingest a synthetic archetype. Every figure produced is illustrative."""
    if req.archetype not in ARCHETYPES:
        raise HTTPException(404, f"unknown archetype: {req.archetype}")
    engine = get_engine()
    as_of = req.as_of or DEMO_AS_OF
    arch = ARCHETYPES[req.archetype]
    token, txns = SyntheticGenerator().generate(
        req.archetype, months=req.months, end=as_of,
        customer_token=req.customer_token,
    )
    engine.consent.grant_defaults(token, as_of=as_of)
    from ...core.money import rupees

    state = engine.ingest(
        token, txns, as_of=as_of, balance_paise=rupees(arch.opening_balance),
        age=arch.age, dependants=arch.dependants, thin_file=arch.thin_file,
        district=arch.district, is_rural=arch.is_rural,
        tenure_with_bank_months=36, on_time_emi_streak=14,
    )
    payload = _profile_payload(state)
    payload["archetype"] = {"key": req.archetype, "label": arch.label}
    payload["data_provenance"] = "SYNTHETIC — illustrative only (report §11.1)"
    return payload


@router.post("/decide")
def decide(req: DecideRequest) -> dict:
    engine = get_engine()
    try:
        bundle = engine.decide(
            req.customer_token,
            as_of=req.as_of or DEMO_AS_OF,
            requested_product_id=req.requested_product_id,
            requested_amount_paise=req.requested_amount_paise,
            missed_payment=req.missed_payment,
            language=req.language,
        )
    except KeyError as exc:
        raise HTTPException(404, f"no ingested state for {req.customer_token}") from exc

    d = bundle.decision
    customer = d.render_customer(req.language)

    payload: dict = {
        "decision_id": d.decision_id,
        "outcome": d.outcome.value,
        "recovery_state": d.recovery_state.value,
        # The supervisory position, beside the behavioural one. Surfaced at the
        # top level rather than only inside the regulator rendering, because the
        # distance between the two ladders is the thing worth looking at and a
        # surface that has to dig for one of them will show neither.
        "supervisory": d.supervisory_gap.render(),
        "customer": {
            "language": customer.language,
            "headline": customer.headline,
            "detail": customer.detail,
            "counterfactual": customer.counterfactual,
            "spoken": customer.spoken,
            "privacy_note": customer.privacy_note,
        },
        "regulator": d.render_regulator(),
        "privacy_ledger": bundle.privacy_ledger,
        "moments": [
            {"trigger": m.trigger, "description": m.description,
             "priority": m.priority, "products": list(m.product_ids)}
            for m in bundle.moments
        ],
        "suppressed_candidates": list(bundle.suppressed_candidates),
        "is_adverse_action": d.is_adverse_action,
        "data_provenance": "Figures illustrative; generated from synthetic data (report §11.2)",
    }

    if bundle.sentinel:
        s = bundle.sentinel
        payload["sentinel"] = {
            "verdict": s.verdict.value,
            "pd_uplift_90d": s.pd_uplift_90d,
            "anomaly_score": s.anomaly_score,
            "pay_intent": s.pay_intent.value,
            "lead_time_days": s.lead_time_days,
            "evidence": list(s.evidence),
            "contact_recommended": s.contact_recommended,
            "fraud_signals": [
                {"pattern": f.pattern, "description": f.description,
                 "response": f.response, "severity": f.severity,
                 "cooling_off_minutes": f.cooling_off_minutes}
                for f in s.fraud_signals
            ],
        }

    if bundle.ladder:
        r = bundle.ladder.recommended
        payload["intervention"] = {
            "withheld_reason": bundle.ladder.withheld_reason,
            "recommended": (
                {
                    "rung": int(r.rung), "name": r.name, "description": r.description,
                    "customer_sentence": r.customer_sentence,
                    "regulatory_cost": r.regulatory_cost,
                    "reg_cost": r.reg_cost.name,
                    "auto_proposable": r.reg_cost.auto_proposable,
                    "requires_human_credit_officer":
                        r.reg_cost.requires_human_credit_officer,
                    "economic_cost": format_inr(r.economic_cost_paise),
                    "reversible": r.reversible,
                    "new_emi": format_inr(r.new_emi_paise) if r.new_emi_paise else None,
                    "new_day_of_month": r.new_day_of_month,
                    "additional_total_cost": format_inr(r.additional_total_cost_paise),
                } if r else None
            ),
            "alternatives": [
                {"rung": int(a.rung), "name": a.name,
                 "regulatory_cost": a.regulatory_cost,
                 "reg_cost": a.reg_cost.name,
                 "requires_human_credit_officer":
                     a.reg_cost.requires_human_credit_officer,
                 "economic_cost": format_inr(a.economic_cost_paise)}
                for a in bundle.ladder.alternatives
            ],
        }

    if d.offer:
        kfs = build_kfs(d.offer, lang=customer.language)
        payload["offer"] = {
            "product_id": d.offer.product.product_id,
            "product_name": d.offer.product.name,
            "family": d.offer.product.family.value,
            "amount": format_inr(d.offer.amount_paise),
            "amount_paise": d.offer.amount_paise,
            "eligible_amount": format_inr(d.offer.eligible_amount_paise),
            "reduced_from_eligibility": d.offer.is_reduced_from_eligibility,
            "tenure_months": d.offer.tenure_months,
            "emi": format_inr(d.offer.emi_paise),
            "emi_paise": d.offer.emi_paise,
            "day_of_month": d.offer.day_of_month,
            "annual_rate": d.offer.annual_rate,
            "total_interest": format_inr(d.offer.total_interest_paise),
            "rationale": d.offer.rationale,
        }
        payload["kfs"] = kfs.as_dict()
        # Presenting an offer is itself a capability, minted rather than assumed.
        token = get_broker().mint(
            Capability.PRESENT_OFFER,
            decision_id=d.decision_id, customer_token=d.customer_token,
            requires_customer_confirmation=False,
        )
        payload["capability_token"] = {
            "token_id": token.token_id,
            "capability": token.capability.value,
            "expires_at": token.expires_at,
            "requires_customer_confirmation": token.requires_customer_confirmation,
        }

    if d.twin:
        payload["twin"] = {
            "verdict": d.twin.verdict,
            "sentence": d.twin.sentence_en,
            "safe_buffer": format_inr(d.twin.safe_buffer_paise),
            "safe_buffer_paise": d.twin.safe_buffer_paise,
            "lowest_projected": format_inr(d.twin.min_balance_p05_paise),
            "breach_probability": d.twin.breach_probability,
            "baseline_breach_probability": d.twin.baseline_breach_probability,
            "resilience_score": d.twin.resilience_score,
            "shocks_absorbed": d.twin.shocks_absorbed,
            "first_breach_date": d.twin.first_breach_date,
            "scenarios": [dict(s) for s in d.twin.scenarios],
            "path_with": list(d.twin.path_with),
            "path_without": list(d.twin.path_without),
            "path_p05": list(d.twin.path_p05),
        }

    return payload


@router.post("/render")
def render(req: RenderRequest) -> dict:
    """Validate a candidate model phrasing through the AI Firewall.

    This endpoint is how a language model participates at all: it proposes text,
    and the firewall decides whether the customer ever hears it (report §7.7).
    """
    engine = get_engine()

    # Reconstruct the decision the model was phrasing, from its audit record.
    #
    # Re-running `decide()` here would be simpler and wrong twice over: the
    # numerals would be checked against a ground the model never saw, and a
    # read-only validation call would mutate state — recording a new decision
    # and consuming the customer's nudge budget.
    record = next(
        (
            r for r in reversed(engine.audit.for_customer(req.customer_token))
            if r.record_type is RecordType.DECISION
            and r.payload.get("decision_id") == req.decision_id
        ),
        None,
    )
    if record is None:
        raise HTTPException(404, f"decision {req.decision_id} not found in the audit log")

    decision = DecisionObject.from_regulator_rendering(record.payload)
    if req.language:
        decision = replace(decision, language=req.language)

    verdict = get_firewall().validate(req.model_text, decision)
    return {
        "outcome": verdict.outcome.value,
        "allowed": verdict.allowed,
        "delivered_text": verdict.text,
        "blocked_detail": verdict.blocked_detail,
        "ungrounded_numbers": list(verdict.ungrounded),
        "used_fallback": verdict.used_fallback,
        "model_context": build_model_context(decision, req.language or "en"),
    }


def _profile_payload(state) -> dict:
    p = state.profile
    enr = state.enrichment
    return {
        "customer_token": p.customer_token,
        "transactions": len(state.transactions),
        "income_type": p.income_type.value,
        "income_type_confidence": p.income_type_confidence,
        "income_type_overridden": p.income_type_overridden,
        "income_evidence": list(enr.income.evidence),
        "posture": p.posture.value,
        "balance": format_inr(p.balance_paise),
        "balance_paise": p.balance_paise,
        "monthly_income": format_inr(p.monthly_income_paise),
        "monthly_committed_outflow": format_inr(p.monthly_committed_outflow_paise),
        "monthly_discretionary": format_inr(p.monthly_discretionary_paise),
        "existing_emi": format_inr(p.existing_emi_paise),
        "obligation_to_income": round(p.obligation_to_income, 4),
        "income_day_of_month": p.income_day_of_month,
        "income_day_dispersion": p.income_day_dispersion,
        "unclassified_share": enr.unclassified_share,
        "injection_findings": len(enr.injection_findings),
        "series": [
            {
                "series_id": s.series_id, "category": s.category.value,
                "direction": s.direction.value, "label": s.label,
                "median_amount": format_inr(s.median_amount_paise),
                "period_days": s.period_days, "day_of_month": s.day_of_month,
                "occurrences": s.occurrences, "drifting": s.drifting,
                "evidence_dates": [d.isoformat() for d in s.evidence_dates],
            }
            for s in p.series
        ],
    }
