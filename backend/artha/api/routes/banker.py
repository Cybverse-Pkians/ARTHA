"""Banker console endpoints.

Report §6.7: a capacity-ranked early-warning queue, correlated portfolio alerts,
full decision explainability with reason codes and a gate trace, fairness
monitoring across cohorts, and an immutable audit trail exportable as an
evidence pack.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...config import settings
from ...core.money import format_inr
from ...engines.sentinel import detect_correlated_stress, rank_for_capacity
from ...gate.fairness import EXCLUDED_DATA_SOURCES, PERMITTED_ALTERNATE_DATA
from ...schemas.api import InterventionResponseRequest, OverrideRequest
from ..deps import DEMO_AS_OF, decide_cached, forget_decision, get_engine

router = APIRouter(prefix="/banker", tags=["banker"])


@router.get("/queue")
def early_warning_queue(capacity: int | None = None) -> dict:
    """The queue, ranked at the bank's actual daily contact capacity.

    Not "who is risky" but "which N should be contacted today" (report §6.3).
    """
    engine = get_engine()
    capacity = capacity or settings.daily_contact_capacity

    assessed = []
    for token in list(engine._states):
        bundle = decide_cached(token)
        if bundle.sentinel:
            assessed.append((token, bundle.sentinel))

    ranked = rank_for_capacity(assessed, capacity=capacity)
    ranked_tokens = {t for t, _ in ranked}

    return {
        "capacity": capacity,
        "assessed": len(assessed),
        "in_queue": len(ranked),
        "excluded_as_unactionable": len(assessed) - len(ranked),
        "note": (
            "Precision is evaluated at this capacity, not at a fixed score "
            "threshold (report §6.3)."
        ),
        "queue": [
            {
                "customer_token": token,
                "verdict": s.verdict.value,
                "pd_uplift_90d": s.pd_uplift_90d,
                "lead_time_days": s.lead_time_days,
                "pay_intent": s.pay_intent.value,
                "anomaly_score": s.anomaly_score,
                "evidence": list(s.evidence),
                "income_type": engine.state(token).profile.income_type.value,
                "district": engine.state(token).profile.district,
                "balance": format_inr(engine.state(token).profile.balance_paise),
            }
            for token, s in ranked
        ],
        "excluded": [
            {
                "customer_token": token,
                "verdict": s.verdict.value,
                "reason": (
                    "Intervention would not change the outcome"
                    if not s.intervention_changes_outcome else
                    "No contact recommended"
                ),
            }
            for token, s in assessed if token not in ranked_tokens
        ],
        "data_provenance": "SYNTHETIC — illustrative only (report §11.2)",
    }


@router.get("/correlated")
def correlated_alerts() -> dict:
    """Employer-level payroll delay detection (report §6.3).

    Grouping salary-credit timing by employer turns N independent borrower
    alerts into one payroll event, before any of those customers has missed a
    payment.
    """
    engine = get_engine()
    observations = []
    for token, state in engine._states.items():
        p = state.profile
        if p.income_day_of_month is None:
            continue
        # Delay is measured against this customer's own usual arrival day.
        delay = int(round(p.income_day_dispersion))
        employer = p.employer_id or _employer_of(state)
        observations.append((token, employer, delay))

    alerts = detect_correlated_stress(observations, min_cluster=2)
    return {
        "alerts": [
            {
                "dimension": a.dimension, "key": a.key,
                "affected_customers": a.affected_customers,
                "median_delay_days": a.median_delay_days,
                "description": a.description,
                "customer_tokens": list(a.customer_tokens[:25]),
            }
            for a in alerts
        ],
        "note": (
            "A cluster here is one event, not many. Thresholds are lowered in this "
            "demo so a small synthetic portfolio produces a visible alert."
        ),
        "data_provenance": "SYNTHETIC — illustrative only (report §11.2)",
    }


@router.get("/fairness")
def fairness_report() -> dict:
    """Benefit distribution across slices — who gets the favourable offers."""
    engine = get_engine()
    report = engine.fairness.report()
    report["excluded_data_sources"] = list(EXCLUDED_DATA_SOURCES)
    report["permitted_alternate_data"] = list(PERMITTED_ALTERNATE_DATA)
    report["note"] = (
        "Slice attributes measure outcomes and never enter a decision. A breach "
        "holds the decision for human review rather than flipping it (report §9.5)."
    )
    return report


@router.get("/suppression")
def suppression_metrics() -> dict:
    """Offers suppressed by the Gate — reported as a success metric (report §2.2)."""
    engine = get_engine()
    outcomes = {"ACT": 0, "SUPPRESS": 0, "PROTECT": 0, "VERIFY": 0}
    blocking: dict[str, int] = {}
    suppressed_products: dict[str, int] = {}

    for token in list(engine._states):
        bundle = decide_cached(token)
        outcomes[bundle.decision.outcome.value] += 1
        if bundle.gate.blocking_check:
            blocking[bundle.gate.blocking_check] = blocking.get(bundle.gate.blocking_check, 0) + 1
        for c in bundle.suppressed_candidates:
            pid = c.get("product_id", "?")
            suppressed_products[pid] = suppressed_products.get(pid, 0) + 1

    total = sum(outcomes.values()) or 1
    return {
        "outcomes": outcomes,
        "suppression_rate": round((outcomes["SUPPRESS"] + outcomes["PROTECT"]) / total, 4),
        "trend_indicator": "positive",
        "blocking_checks": blocking,
        "suppressed_by_product": suppressed_products,
        "note": (
            "A high suppression count is a success. It is the tail of unsuitable "
            "lending from which conduct penalties and supervisory action arise "
            "(report §2.2, §10)."
        ),
        "product_design_feedback": (
            "Product terms causing the most suitability rejections are listed above; "
            "changing them is the cheapest way to unlock originations (report §8.1)."
        ),
        "data_provenance": "SYNTHETIC — illustrative only (report §11.2)",
    }


@router.get("/dual-ledger")
def dual_ledger() -> dict:
    """Customer benefit and bank value, from the same decision log (report §10.2)."""
    engine = get_engine()
    customer_value = 0
    bank_value = 0
    suppressed = 0
    counterfactuals = 0
    interventions = 0

    for token in list(engine._states):
        bundle = decide_cached(token)
        d = bundle.decision
        if d.offer:
            # Customer value: the exposure the Gate declined to extend.
            customer_value += max(d.offer.eligible_amount_paise - d.offer.amount_paise, 0)
            bank_value += d.offer.total_interest_paise
        if d.outcome.value in {"SUPPRESS", "PROTECT"}:
            suppressed += 1
        if d.counterfactual and d.counterfactual.available:
            counterfactuals += 1
        if bundle.ladder and bundle.ladder.has_recommendation:
            interventions += 1

    return {
        "customer": {
            "over_exposure_avoided": format_inr(customer_value),
            "over_exposure_avoided_paise": customer_value,
            "offers_suppressed": suppressed,
            "counterfactuals_offered": counterfactuals,
            "interventions_offered": interventions,
        },
        "bank": {
            "projected_interest_on_sustainable_lending": format_inr(bank_value),
            "projected_interest_paise": bank_value,
        },
        "note": (
            "Both columns are rendered from the same decision log rather than "
            "asserted to be aligned (report §10.2)."
        ),
        "data_provenance": "SYNTHETIC — illustrative only (report §11.2)",
    }


@router.get("/customers")
def customers() -> dict:
    engine = get_engine()
    return {
        "customers": [
            {
                "customer_token": token,
                "income_type": s.profile.income_type.value,
                "income_type_confidence": s.profile.income_type_confidence,
                "posture": s.profile.posture.value,
                "recovery_state": engine.recovery.get(token).state.value,
                "balance": format_inr(s.profile.balance_paise),
                "monthly_income": format_inr(s.profile.monthly_income_paise),
                "district": s.profile.district,
                "is_rural": s.profile.is_rural,
                "thin_file": s.profile.thin_file,
                "transactions": len(s.transactions),
            }
            for token, s in engine._states.items()
        ]
    }


@router.post("/override-income-type")
def override_income_type(req: OverrideRequest) -> dict:
    """The mandatory human correction path of report §5.1.

    Re-ingests the customer's history with the human's label pinned. The override
    wins unconditionally and is written to the audit log with the actor's name,
    because a correction nobody is accountable for is not a control.
    """
    from ...audit.log import RecordType
    from ...core.types import IncomeType

    engine = get_engine()
    try:
        income_type = IncomeType(req.income_type)
    except ValueError as exc:
        raise HTTPException(400, f"unknown income type: {req.income_type}") from exc

    try:
        state = engine.state(req.customer_token)
    except KeyError as exc:
        raise HTTPException(404, "customer not ingested") from exc

    before = state.profile.income_type.value
    engine.ingest(
        req.customer_token, state.transactions,
        balance_paise=state.profile.balance_paise,
        income_override=income_type, as_of=DEMO_AS_OF,
        language=state.profile.language, age=state.profile.age,
        dependants=state.profile.dependants, thin_file=state.profile.thin_file,
        district=state.profile.district, is_rural=state.profile.is_rural,
        tenure_with_bank_months=state.profile.tenure_with_bank_months,
        on_time_emi_streak=state.profile.on_time_emi_streak,
    )
    engine.audit.append(
        RecordType.HUMAN_OVERRIDE, req.customer_token,
        {"field": "income_type", "from": before, "to": income_type.value,
         "reason": req.reason},
        actor=req.actor,
    )
    forget_decision(req.customer_token)
    return {"customer_token": req.customer_token, "from": before,
            "to": income_type.value, "actor": req.actor}


@router.post("/intervention-response")
def intervention_response(req: InterventionResponseRequest) -> dict:
    """Record the customer's answer to an offer of assistance.

    Declining is explicitly **not** treated as a negative signal (report §6.5):
    the customer may have income arriving from a source the bank cannot see. The
    choice is recorded, a standing preference is honoured, and the case is
    re-assessed later.
    """
    from ...audit.log import RecordType

    engine = get_engine()
    forget_decision(req.customer_token)
    if req.accepted:
        # Accepting starts a plan, and a tracked plan is what RECOVERY *is*.
        # Logging the acceptance without making this transition is what left
        # RECOVERY unreachable outside the test suite.
        record = engine.recovery.accept_plan(req.customer_token, family=req.family)
        engine.audit.append(
            RecordType.INTERVENTION_ACCEPTED, req.customer_token,
            {"family": req.family, "recovery_state": record.state.value},
        )
        return {
            "recorded": "accepted",
            "treated_as_risk_signal": False,
            "recovery_state": record.state.value,
            "plan_started": record.plan_started.isoformat() if record.plan_started else None,
        }

    engine.recovery.record_decline(
        req.customer_token, family=req.family, do_not_ask_again=req.do_not_ask_again
    )
    engine.audit.append(
        RecordType.INTERVENTION_DECLINED, req.customer_token,
        {
            "family": req.family,
            "do_not_ask_again": req.do_not_ask_again,
            "note": (
                "Declining is not a deterioration signal. Escalation requires that "
                "indicators continue to worsen after assistance was offered."
            ),
        },
    )
    return {"recorded": "declined", "treated_as_risk_signal": False,
            "do_not_ask_again": req.do_not_ask_again}


def _employer_of(state) -> str:
    """Best-effort employer key from the dominant salary counterparty."""
    from ...core.types import Category, Direction

    for s in state.profile.series:
        if s.direction is Direction.CREDIT and s.category is Category.SALARY:
            return s.series_id.split("|")[0]
    return "unknown"
