"""The vernacular, zero-typing journey.

Report §6.2. The journey is voice-first because the target user does not type
comfortably in a second language. The assistant conducts the conversation,
requests purpose-scoped consent aloud, retrieves records through the Account
Aggregator and documents from DigiLocker, and fills the application itself. The
customer types nothing and only confirms.

Everything in this module exists because of a specific, named drop-off:

* **Resumable state** — sessions are abandoned on missing documents and poor
  connectivity, so journey state is persisted and resumes through WhatsApp or an
  IVR callback.
* **Video-KYC pre-flight** — a thirty-second readiness test for lighting,
  connectivity and documents, run *before* a slot is booked, since those are the
  conditions on which such calls commonly fail.
* **Degradation ladder** — app, then WhatsApp, then IVR, then SMS and USSD. The
  journey completes on a low-end feature phone.
* **Assisted mode** — in much of rural India a business correspondent operates
  the journey, so a three-way session is supported in which the assistant reads
  the Key Fact Statement directly to the customer and the intermediary cannot
  misrepresent the terms.
* **Anti-phishing by design** — the assistant displays a customer-chosen safety
  phrase in every session and states visibly that it will never ask for an OTP,
  PIN or CVV, because a bank assistant is itself a phishing surface.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from ..core.types import ChannelSegment


class Stage(str, Enum):
    GREETING = "GREETING"
    LANGUAGE_SELECT = "LANGUAGE_SELECT"
    CONSENT = "CONSENT"
    PURPOSE_CAPTURE = "PURPOSE_CAPTURE"
    AMOUNT_CAPTURE = "AMOUNT_CAPTURE"
    AA_FETCH = "AA_FETCH"
    DOCUMENT_FETCH = "DOCUMENT_FETCH"
    AFFORDABILITY_REVIEW = "AFFORDABILITY_REVIEW"     # the Twin chart *is* the consent screen
    KFS_READING = "KFS_READING"
    VIDEO_KYC_PREFLIGHT = "VIDEO_KYC_PREFLIGHT"
    VIDEO_KYC = "VIDEO_KYC"
    CONFIRMATION = "CONFIRMATION"
    COMPLETE = "COMPLETE"
    ABANDONED = "ABANDONED"


class Channel(str, Enum):
    """The degradation ladder, in order."""

    APP = "APP"
    WHATSAPP = "WHATSAPP"
    IVR = "IVR"
    SMS = "SMS"
    USSD = "USSD"


DEGRADATION_LADDER: tuple[Channel, ...] = (
    Channel.APP, Channel.WHATSAPP, Channel.IVR, Channel.SMS, Channel.USSD,
)

# What each channel can actually carry. The Twin chart cannot be shown over
# USSD, so the affordability explanation degrades to a spoken sentence — which
# is why the Twin produces one (report §5.1) rather than only a chart.
CHANNEL_CAPABILITIES: dict[Channel, set[str]] = {
    Channel.APP: {"chart", "voice", "text", "video", "deeplink"},
    Channel.WHATSAPP: {"chart", "voice", "text", "deeplink"},
    Channel.IVR: {"voice"},
    Channel.SMS: {"text"},
    Channel.USSD: {"text"},
}


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str
    remedy: str = ""


@dataclass(frozen=True)
class PreflightResult:
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def blockers(self) -> tuple[PreflightCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)


def video_kyc_preflight(
    *,
    lighting_lux: float,
    bandwidth_kbps: float,
    has_pan: bool,
    has_aadhaar_ref: bool,
    front_camera: bool,
    battery_percent: int,
) -> PreflightResult:
    """Thirty-second readiness test, run before a slot is booked.

    Booking a slot the customer cannot keep costs them a wasted appointment and
    the bank a wasted agent, and it is the most common way a completed
    application still fails to become an account.
    """
    checks = (
        PreflightCheck(
            "lighting", lighting_lux >= 120,
            f"Ambient light {lighting_lux:.0f} lux.",
            "Move to a brighter spot or face a window.",
        ),
        PreflightCheck(
            "bandwidth", bandwidth_kbps >= 256,
            f"Uplink {bandwidth_kbps:.0f} kbps.",
            "Move closer to the window, or book a branch visit instead.",
        ),
        PreflightCheck("pan", has_pan, "PAN available.", "Fetch PAN from DigiLocker first."),
        PreflightCheck(
            "identity", has_aadhaar_ref, "Identity reference available.",
            "Complete the DigiLocker link before booking.",
        ),
        PreflightCheck("camera", front_camera, "Front camera available.",
                       "Use a device with a front camera, or visit a branch."),
        PreflightCheck(
            "battery", battery_percent >= 20, f"Battery {battery_percent}%.",
            "Charge above 20% before the call.",
        ),
    )
    return PreflightResult(checks)


@dataclass
class JourneySession:
    """One customer journey, resumable across channels.

    ``safety_phrase`` is chosen by the customer once and shown in every session.
    If it is absent, the session is not ARTHA — which is the only anti-phishing
    control that works against an attacker who can imitate everything else.
    """

    session_id: str
    customer_token: str
    language: str = "hi"
    channel: Channel = Channel.APP
    segment: ChannelSegment = ChannelSegment.APP_NATIVE
    stage: Stage = Stage.GREETING
    safety_phrase: str = ""
    assisted_by: str | None = None            # business-correspondent id
    slots: dict[str, object] = field(default_factory=dict)
    prefilled: dict[str, dict[str, str]] = field(default_factory=dict)
    completed_stages: list[str] = field(default_factory=list)
    pending_document: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    abandon_stage: str | None = None

    NEVER_ASKS = ("OTP", "PIN", "CVV", "password", "card number")

    # ------------------------------------------------------------- lifecycle

    def advance(self, to: Stage) -> "JourneySession":
        self.completed_stages.append(self.stage.value)
        self.stage = to
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        return self

    def abandon(self) -> "JourneySession":
        self.abandon_stage = self.stage.value
        self.stage = Stage.ABANDONED
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        return self

    def resume(self, channel: Channel | None = None) -> "JourneySession":
        """Resume an abandoned journey, possibly on a different channel.

        The customer does not restart. Report §6.2 lists drop-off recovery as a
        named feature precisely because making somebody re-enter everything is
        how a recovered session becomes a second abandonment.
        """
        if self.abandon_stage:
            self.stage = Stage(self.abandon_stage)
            self.abandon_stage = None
        if channel:
            self.channel = channel
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        return self

    def degrade(self) -> "JourneySession":
        """Step one rung down the delivery ladder."""
        idx = DEGRADATION_LADDER.index(self.channel)
        if idx + 1 < len(DEGRADATION_LADDER):
            self.channel = DEGRADATION_LADDER[idx + 1]
            self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        return self

    # ------------------------------------------------------------- prefilling

    def prefill(self, field_name: str, value: str, source: str) -> None:
        """Fill a field, recording where it came from.

        Report §6.2: every pre-filled field is labelled with the authoritative
        source it came from. A customer confirming a form they did not fill is
        entitled to know whether a number came from their own bank, from an
        Account Aggregator pull or from DigiLocker.
        """
        self.prefilled[field_name] = {"value": value, "source": source}

    def unsourced_fields(self) -> list[str]:
        """Fields with no recorded provenance — none should ever exist."""
        return [k for k, v in self.prefilled.items() if not v.get("source")]

    # ------------------------------------------------------------ anti-phish

    def ensure_safety_phrase(self) -> str:
        if not self.safety_phrase:
            self.safety_phrase = _generate_safety_phrase()
        return self.safety_phrase

    def session_banner(self) -> dict:
        return {
            "safety_phrase": self.ensure_safety_phrase(),
            "never_asks": list(self.NEVER_ASKS),
            "notice": (
                "इस संदेश में आपका सुरक्षा वाक्यांश है। हम कभी OTP, PIN या CVV नहीं मांगेंगे।"
                if self.language == "hi" else
                "This message carries your safety phrase. We will never ask for your "
                "OTP, PIN or CVV."
            ),
            "assisted_by": self.assisted_by,
            "assisted_notice": (
                (
                    "इस सत्र को एक बैंक मित्र चला रहा है। मुख्य तथ्य विवरण सीधे आपको पढ़ा जाएगा।"
                    if self.language == "hi" else
                    "A bank representative is operating this session. The Key Fact "
                    "Statement will be read directly to you, not to them."
                )
                if self.assisted_by else None
            ),
        }

    # ---------------------------------------------------------------- render

    def can_render(self, capability: str) -> bool:
        return capability in CHANNEL_CAPABILITIES[self.channel]

    def affordability_presentation(self) -> str:
        """How to present the Twin on this channel.

        The chart is the explanation and the consent screen where it can be
        shown. Where it cannot, the Twin's plain-language sentence carries the
        same content — which is why that sentence is computed rather than
        decorative.
        """
        if self.can_render("chart"):
            return "chart"
        if self.can_render("voice"):
            return "spoken_sentence"
        return "sms_summary"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "customer_token": self.customer_token,
            "language": self.language,
            "channel": self.channel.value,
            "segment": self.segment.value,
            "stage": self.stage.value,
            "completed_stages": list(self.completed_stages),
            "slots": dict(self.slots),
            "prefilled": dict(self.prefilled),
            "pending_document": self.pending_document,
            "assisted_by": self.assisted_by,
            "banner": self.session_banner(),
            "affordability_presentation": self.affordability_presentation(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# A short, memorable, unambiguous phrase. Words are chosen to be easy to read
# aloud over a bad line and hard to confuse with one another.
_PHRASE_WORDS = (
    "peacock", "mango", "river", "lantern", "tiger", "monsoon", "jasmine",
    "kite", "banyan", "harbour", "saffron", "compass",
)


def _generate_safety_phrase() -> str:
    return " ".join(secrets.choice(_PHRASE_WORDS) for _ in range(2))


class JourneyStore:
    """In-process session store. A deployment backs this with the operational
    database so a session survives a restart and can resume on another channel."""

    def __init__(self) -> None:
        self._sessions: dict[str, JourneySession] = {}

    def create(
        self, customer_token: str, *, language: str = "hi",
        channel: Channel = Channel.APP, assisted_by: str | None = None,
        segment: ChannelSegment = ChannelSegment.APP_NATIVE,
    ) -> JourneySession:
        session_id = f"jrn_{secrets.token_hex(8)}"
        session = JourneySession(
            session_id=session_id, customer_token=customer_token,
            language=language, channel=channel, assisted_by=assisted_by,
            segment=segment,
        )
        session.ensure_safety_phrase()
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> JourneySession:
        if session_id not in self._sessions:
            raise KeyError(session_id)
        return self._sessions[session_id]

    def for_customer(self, customer_token: str) -> list[JourneySession]:
        return [s for s in self._sessions.values() if s.customer_token == customer_token]

    def abandoned(self) -> list[JourneySession]:
        return [s for s in self._sessions.values() if s.stage is Stage.ABANDONED]


DEFAULT_STORE = JourneyStore()
