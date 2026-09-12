"""Audit and evidence-pack endpoints (report §6.7, §9.4)."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import get_engine

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify")
def verify() -> dict:
    engine = get_engine()
    ok, detail = engine.audit.verify()
    return {
        "verified": ok,
        "detail": detail,
        "records": len(engine.audit),
        "note": "Records are hash-chained; any alteration breaks the chain verifiably.",
    }


@router.get("/evidence/{customer_token}")
def evidence_pack(customer_token: str) -> dict:
    """Everything a supervisor would ask for about one customer.

    Stress observations and interventions are separate sections on purpose:
    detection is unconditional and forbearance is a distinct, separately logged
    decision, which is the structural answer to an evergreening reading
    (report §9.4).
    """
    return get_engine().audit.evidence_pack(customer_token)


@router.get("/records")
def records(limit: int = 100, record_type: str | None = None) -> dict:
    engine = get_engine()
    rows = list(engine.audit.records)
    if record_type:
        rows = [r for r in rows if r.record_type.value == record_type]
    rows = rows[-limit:]
    return {
        "count": len(rows),
        "records": [
            {
                "seq": r.seq, "type": r.record_type.value,
                "customer_token": r.customer_token, "at": r.at,
                "actor": r.actor, "hash": r.hash[:16],
                "payload_keys": sorted(r.payload.keys()),
            }
            for r in rows
        ],
    }
