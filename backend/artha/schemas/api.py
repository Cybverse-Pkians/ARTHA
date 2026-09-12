"""Request and response models for the decision API.

Deliberately thin. The API is a transport for the Decision Object, not a second
place where decisions get shaped — anything that changes an outcome belongs in
the orchestrator, where it is covered by the engine tests.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class IngestTransaction(BaseModel):
    txn_id: str
    ts: str
    amount_paise: int = Field(..., description="Signed; negative is a debit")
    narration: str
    channel: str = "UPI"
    balance_after_paise: int | None = None
    counterparty_vpa: str | None = None
    counterparty_name: str | None = None


class IngestRequest(BaseModel):
    customer_token: str
    transactions: list[IngestTransaction]
    balance_paise: int | None = None
    language: str = "hi"
    age: int | None = None
    dependants: int = 0
    thin_file: bool = False
    district: str = ""
    is_rural: bool = False
    gender: str | None = Field(
        None, description="Fairness slice only; never reaches the decision profile."
    )
    tenure_with_bank_months: int = 0
    on_time_emi_streak: int = 0
    credit_utilisation: float = 0.0
    has_term_cover: bool = False
    has_health_cover: bool = False
    income_type_override: str | None = Field(
        None, description="Human correction path (report §5.1). Wins unconditionally."
    )
    as_of: date | None = None


class DecideRequest(BaseModel):
    customer_token: str
    requested_product_id: str | None = None
    requested_amount_paise: int | None = None
    missed_payment: bool = False
    language: str | None = None
    as_of: date | None = None


class SeedRequest(BaseModel):
    archetype: str = "salaried_stable"
    months: int = 14
    as_of: date | None = None
    customer_token: str | None = None


class RenderRequest(BaseModel):
    """Ask the firewall to validate a candidate phrasing against a decision."""

    decision_id: str
    customer_token: str
    model_text: str
    language: str | None = None


class ConsentRequest(BaseModel):
    customer_token: str
    purpose: str
    grant: bool = True


class OverrideRequest(BaseModel):
    customer_token: str
    income_type: str
    actor: str
    reason: str


class JourneyStartRequest(BaseModel):
    customer_token: str
    language: str = "hi"
    channel: str = "APP"
    assisted_by: str | None = None


class JourneyAdvanceRequest(BaseModel):
    session_id: str
    stage: str | None = None
    degrade: bool = False
    abandon: bool = False
    resume: bool = False


class SlotRequest(BaseModel):
    text: str
    asr_confidence: float = 0.9
    language: str = "hi"
    slot: str = "AMOUNT"


class PreflightRequest(BaseModel):
    lighting_lux: float = 200
    bandwidth_kbps: float = 512
    has_pan: bool = True
    has_aadhaar_ref: bool = True
    front_camera: bool = True
    battery_percent: int = 70


class InterventionResponseRequest(BaseModel):
    customer_token: str
    accepted: bool
    do_not_ask_again: bool = False
    family: str | None = None
