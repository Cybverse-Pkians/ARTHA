"""Catalogue and reference-data endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ...core.money import SUPPORTED_LANGUAGES, format_inr
from ...core.reason_codes import all_codes
from ...gate.fairness import EXCLUDED_DATA_SOURCES, PERMITTED_ALTERNATE_DATA
from ...products.catalogue import CATALOGUE
from ...synth.generator import ARCHETYPES

router = APIRouter(tags=["reference"])


@router.get("/catalogue")
def catalogue() -> dict:
    return {
        "products": [
            {
                "product_id": p.product_id, "name": p.name, "family": p.family.value,
                "min_amount": format_inr(p.min_amount_paise),
                "max_amount": format_inr(p.max_amount_paise),
                "annual_rate": p.annual_rate, "tenures": list(p.tenures),
                "description": p.description,
                "replaces_high_cost": p.replaces_high_cost,
                "requires_monthly_repayment": p.requires_monthly_repayment,
                "eligibility_rules": [
                    {"name": r.name, "description": r.description} for r in p.rules
                ],
            }
            for p in CATALOGUE
        ]
    }


@router.get("/reason-codes")
def reason_codes() -> dict:
    return {
        "codes": [
            {
                "code": spec.code, "title": spec.title, "description": spec.description,
                "polarity": spec.polarity.value, "adverse_action": spec.adverse_action,
                "languages": sorted(spec.templates.keys()),
            }
            for spec in sorted(all_codes().values(), key=lambda s: s.code)
        ]
    }


@router.get("/archetypes")
def archetypes() -> dict:
    return {
        "archetypes": [
            {
                "key": a.key, "label": a.label,
                "expected_income_type": a.expected_income_type.value,
                "tags": list(a.tags),
            }
            for a in ARCHETYPES.values()
        ],
        "data_provenance": "SYNTHETIC — illustrative only (report §11.1, §11.2)",
    }


@router.get("/policy")
def policy() -> dict:
    from ...config import settings

    return {
        "languages": list(SUPPORTED_LANGUAGES),
        "twin": {
            "horizon_days": settings.twin_horizon_days,
            "paths": settings.twin_paths,
            "seed": settings.twin_seed,
            "breach_probability_ceiling": settings.breach_probability_ceiling,
            "min_buffer_days": settings.min_buffer_days,
        },
        "gate": {
            "nudge_budget_per_month": settings.nudge_budget_per_month,
            "product_cooldown_days": settings.product_cooldown_days,
            "obligation_to_income_ceiling": settings.obligation_to_income_ceiling,
        },
        "sentinel": {"daily_contact_capacity": settings.daily_contact_capacity},
        "excluded_data_sources": list(EXCLUDED_DATA_SOURCES),
        "permitted_alternate_data": list(PERMITTED_ALTERNATE_DATA),
        "note": (
            "Gate thresholds are a regulated artefact: a supervisor may ask what the "
            "buffer floor was on a given date, and the answer comes from one "
            "versioned place."
        ),
    }
