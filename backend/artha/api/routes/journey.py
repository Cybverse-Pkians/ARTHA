"""Vernacular journey endpoints — the zero-typing loan application."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...consent.purposes import REGISTRY, Purpose
from ...journey.session import Channel, JourneySession, Stage, video_kyc_preflight
from ...language.adapters import (
    detect_code_mixing,
    extract_amount,
    extract_tenure,
    get_provider,
)
from ...schemas.api import (
    ConsentRequest,
    JourneyAdvanceRequest,
    JourneyStartRequest,
    PreflightRequest,
    SlotRequest,
)
from ..deps import DEMO_AS_OF, get_engine, get_journeys

router = APIRouter(prefix="/journey", tags=["journey"])


@router.post("/start")
def start(req: JourneyStartRequest) -> dict:
    store = get_journeys()
    try:
        channel = Channel(req.channel)
    except ValueError as exc:
        raise HTTPException(400, f"unknown channel: {req.channel}") from exc

    session = store.create(
        req.customer_token, language=req.language, channel=channel,
        assisted_by=req.assisted_by,
    )
    return session.to_dict()


@router.post("/advance")
def advance(req: JourneyAdvanceRequest) -> dict:
    store = get_journeys()
    try:
        session = store.get(req.session_id)
    except KeyError as exc:
        raise HTTPException(404, "session not found") from exc

    if req.abandon:
        session.abandon()
    elif req.resume:
        session.resume()
    elif req.degrade:
        session.degrade()
    elif req.stage:
        try:
            session.advance(Stage(req.stage))
        except ValueError as exc:
            raise HTTPException(400, f"unknown stage: {req.stage}") from exc

    return session.to_dict()


@router.post("/slot")
def slot(req: SlotRequest) -> dict:
    """Confidence-gated slot filling.

    Report §6.2: below the confidence threshold on any amount or date, the
    assistant re-asks rather than guessing. A ₹1,00,000 request misheard as
    ₹10,00,000 is an unacceptable failure mode, so large amounts are read back
    regardless of how confident the recogniser was.
    """
    if req.slot.upper() == "TENURE_MONTHS":
        result = extract_tenure(req.text, req.asr_confidence, req.language)
    else:
        result = extract_amount(req.text, req.asr_confidence, req.language)

    return {
        "slot": result.slot.value,
        "value": result.value,
        "confidence": result.confidence,
        "needs_reask": result.needs_reask,
        "reask_prompt": result.reask_prompt,
        "read_back": result.read_back,
        "code_mixed": detect_code_mixing(req.text),
        "note": (
            "Code-mixed input is a first-class case, not a recognition failure "
            "(report §7.5)."
        ),
    }


@router.post("/video-kyc/preflight")
def preflight(req: PreflightRequest) -> dict:
    """Thirty-second readiness test, run before a slot is booked (report §6.2)."""
    result = video_kyc_preflight(
        lighting_lux=req.lighting_lux, bandwidth_kbps=req.bandwidth_kbps,
        has_pan=req.has_pan, has_aadhaar_ref=req.has_aadhaar_ref,
        front_camera=req.front_camera, battery_percent=req.battery_percent,
    )
    return {
        "ready": result.ready,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail, "remedy": c.remedy}
            for c in result.checks
        ],
        "blockers": [c.name for c in result.blockers],
        "recommendation": (
            "Book the video-KYC slot." if result.ready else
            "Do not book yet — resolve the blockers first, or offer a branch visit."
        ),
    }


@router.get("/consent/{customer_token}")
def consent_state(customer_token: str, lang: str = "hi") -> dict:
    """The consent screen: purposes, in the customer's language, with countdowns."""
    engine = get_engine()
    live = engine.consent.live_purposes(customer_token, as_of=DEMO_AS_OF)
    grants = engine.consent.grants.get(customer_token, {})
    return {
        "customer_token": customer_token,
        "purposes": [
            {
                "purpose": p.value,
                "label": REGISTRY[p].label(lang),
                "legal_basis": REGISTRY[p].legal_basis,
                "withdrawable": REGISTRY[p].withdrawable,
                "live": p in live,
                "days_remaining": (
                    grants[p].days_remaining(DEMO_AS_OF) if p in grants else 0
                ),
            }
            for p in Purpose
        ],
        "note": (
            "Revoking a purpose removes the associated features at inference time, "
            "not merely from a policy document (report §9.1)."
        ),
    }


@router.post("/consent")
def set_consent(req: ConsentRequest) -> dict:
    from ...audit.log import RecordType

    engine = get_engine()
    try:
        purpose = Purpose(req.purpose)
    except ValueError as exc:
        raise HTTPException(400, f"unknown purpose: {req.purpose}") from exc

    if req.grant:
        engine.consent.grant(req.customer_token, purpose, as_of=DEMO_AS_OF)
        action = "granted"
    else:
        ok = engine.consent.revoke(req.customer_token, purpose)
        if not ok:
            raise HTTPException(
                400,
                f"{purpose.value} is not withdrawable: {REGISTRY[purpose].legal_basis}",
            )
        action = "revoked"

    engine.audit.append(
        RecordType.CONSENT_CHANGE, req.customer_token,
        {"purpose": purpose.value, "action": action}, actor="customer",
    )
    return {"purpose": purpose.value, "action": action}


@router.get("/tts")
def tts(text: str, lang: str = "hi") -> dict:
    """Synthesis through the swappable adapter (report §7.5, §9.2)."""
    provider = get_provider()
    result = provider.synthesise(text, lang)
    return {
        "provider": provider.name,
        "audio_ref": result.audio_ref,
        "text": result.text,
        "language": result.language,
        "duration_ms": result.duration_ms,
        "note": (
            "The stub provider does not synthesise or translate. Language coverage "
            "is an integration claim, not a modelling claim (report §11.3)."
        ),
    }
