"""Indian-language service adapters.

Report §7.5 and §8: speech recognition, machine translation and speech synthesis
are consumed through **swappable adapters** over Indian-language stacks, with
government-backed Bhashini services and AI4Bharat open models as the intended
providers.

The adapter boundary is not architectural politeness. Report §9.2 requires that
payment-system data stay in India, so a bank must be able to point these at an
in-country or on-premise deployment without touching anything else. And report
§11.3 is blunt that language coverage is an *integration* claim, not a modelling
claim — so the stub provider below is honest about being a stub, and says so in
its output rather than quietly pretending to translate.

The one piece of real logic here is confidence gating. Report §6.2: below a
confidence threshold on any amount or date, the assistant re-asks rather than
guessing, because a ₹1,00,000 request misheard as ₹10,00,000 is an unacceptable
failure mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from ..config import settings
from ..core.money import SUPPORTED_LANGUAGES, rupees

# Confidence below which the assistant must re-ask rather than proceed.
SLOT_CONFIDENCE_FLOOR = 0.80
# Amounts at or above this always get a spoken read-back, whatever the
# confidence. An order-of-magnitude error is survivable at ₹5,000 and is not at
# ₹5,00,000, so the threshold is on consequence rather than on model certainty.
ALWAYS_CONFIRM_ABOVE_PAISE = rupees(50_000)


@dataclass(frozen=True)
class ASRResult:
    text: str
    language: str
    confidence: float
    alternatives: tuple[str, ...] = field(default_factory=tuple)
    is_code_mixed: bool = False


@dataclass(frozen=True)
class TTSResult:
    audio_ref: str            # opaque handle; audio bytes never enter the decision path
    text: str
    language: str
    duration_ms: int = 0


class LanguageProvider(Protocol):
    name: str

    def transcribe(self, audio_ref: str, language: str) -> ASRResult: ...
    def translate(self, text: str, source: str, target: str) -> str: ...
    def synthesise(self, text: str, language: str) -> TTSResult: ...


class StubProvider:
    """Offline provider used for development and demonstration.

    Deliberately does not fake translation. It returns the source string tagged
    with the requested language so that a demo never shows invented Tamil to a
    Tamil speaker, and so that "what is demonstrated" and "what is architected"
    stay distinguishable at every presentation, as report §11.3 requires.
    """

    name = "stub"

    def transcribe(self, audio_ref: str, language: str) -> ASRResult:
        return ASRResult(text="", language=language, confidence=0.0)

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        return f"[{target}] {text}"

    def synthesise(self, text: str, language: str) -> TTSResult:
        return TTSResult(
            audio_ref=f"stub://tts/{language}",
            text=text,
            language=language,
            duration_ms=len(text) * 55,
        )


class BhashiniProvider:
    """Adapter for Bhashini / AI4Bharat endpoints (IndicTrans2, Indic ASR/TTS).

    Endpoint and key come from configuration so the bank can point this at its
    own in-country deployment. Left unconfigured it raises rather than silently
    degrading — a translation layer that fails open is one that will eventually
    read a Key Fact Statement to somebody in a language they do not speak.
    """

    name = "bhashini"

    def __init__(self, endpoint: str | None = None, api_key: str | None = None) -> None:
        self.endpoint = endpoint or settings.bhashini_endpoint
        self.api_key = api_key or settings.bhashini_api_key
        if not self.endpoint:
            raise RuntimeError(
                "ARTHA_BHASHINI_ENDPOINT is not configured. Set it to an in-country "
                "Bhashini deployment, or use the stub provider explicitly."
            )

    def _post(self, path: str, payload: dict) -> dict:
        import httpx

        response = httpx.post(
            f"{self.endpoint.rstrip('/')}/{path.lstrip('/')}",
            json=payload,
            headers={"Authorization": self.api_key} if self.api_key else {},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    def transcribe(self, audio_ref: str, language: str) -> ASRResult:
        data = self._post("asr", {"audio": audio_ref, "sourceLanguage": language})
        return ASRResult(
            text=data.get("text", ""),
            language=language,
            confidence=float(data.get("confidence", 0.0)),
            alternatives=tuple(data.get("alternatives", [])),
            is_code_mixed=bool(data.get("codeMixed", False)),
        )

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        data = self._post(
            "translate",
            {"text": text, "sourceLanguage": source, "targetLanguage": target},
        )
        return data.get("text", text)

    def synthesise(self, text: str, language: str) -> TTSResult:
        data = self._post("tts", {"text": text, "targetLanguage": language})
        return TTSResult(
            audio_ref=data.get("audioRef", ""),
            text=text,
            language=language,
            duration_ms=int(data.get("durationMs", 0)),
        )


def get_provider(name: str | None = None) -> LanguageProvider:
    provider = (name or settings.language_provider).lower()
    if provider == "bhashini":
        return BhashiniProvider()
    return StubProvider()


# --------------------------------------------------------------- slot filling


class SlotType(str, Enum):
    AMOUNT = "AMOUNT"
    TENURE_MONTHS = "TENURE_MONTHS"
    DATE = "DATE"
    PURPOSE = "PURPOSE"
    YES_NO = "YES_NO"


@dataclass(frozen=True)
class SlotExtraction:
    slot: SlotType
    value: object | None
    confidence: float
    needs_reask: bool
    reask_prompt: str = ""
    read_back: str = ""


# Multipliers for spoken magnitudes, across the scripts a caller may use.
_MAGNITUDE_MULTIPLIERS: tuple[tuple[str, int], ...] = (
    ("crore", 10_000_000), ("करोड़", 10_000_000), ("கோடி", 10_000_000),
    ("కోటి", 10_000_000), ("কোটি", 10_000_000), ("ಕೋಟಿ", 10_000_000),
    ("કરોડ", 10_000_000), ("കോടി", 10_000_000), ("ਕਰੋੜ", 10_000_000),
    ("lakh", 100_000), ("lac", 100_000), ("लाख", 100_000), ("லட்சம்", 100_000),
    ("లక్ష", 100_000), ("লাখ", 100_000), ("ಲಕ್ಷ", 100_000), ("લાખ", 100_000),
    ("ലക്ഷം", 100_000), ("ਲੱਖ", 100_000),
    ("thousand", 1_000), ("hazaar", 1_000), ("हज़ार", 1_000), ("हजार", 1_000),
    ("ஆயிரம்", 1_000), ("వేలు", 1_000), ("হাজার", 1_000), ("ಸಾವಿರ", 1_000),
    ("હજાર", 1_000), ("ആയിരം", 1_000), ("ਹਜ਼ਾਰ", 1_000),
)

_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")

# Spoken numerals.
#
# A voice-first journey cannot assume digits. "Mujhe ek lakh chahiye" is the
# normal way to ask for ₹1,00,000, and a parser that only understands "1 lakh"
# re-asks forever and the customer hangs up — which is the exact drop-off report
# §6.2 is built to prevent.
#
# Production ASR (Bhashini / AI4Bharat) usually applies inverse text
# normalisation and returns digits, so this is a fallback rather than the primary
# path. It is kept because a fallback that silently does nothing is how a
# provider change becomes a field outage.
_WORD_NUMBERS: dict[str, float] = {
    # English
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "twentyfive": 25, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
    # Romanised Hindi / Marathi — how people actually type and speak to a bot
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4,
    "panch": 5, "paanch": 5, "paach": 5, "chhe": 6, "che": 6, "chah": 6,
    "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "no": 9,
    "das": 10, "dus": 10, "gyarah": 11, "barah": 12, "pandrah": 15,
    "bees": 20, "bis": 20, "pachchees": 25, "tees": 30, "chalis": 40,
    "pachas": 50, "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80,
    "nabbe": 90, "sau": 100,
    # Devanagari
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6,
    "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "पंद्रह": 15, "बीस": 20,
    "पच्चीस": 25, "तीस": 30, "चालीस": 40, "पचास": 50, "सौ": 100,
    # Bengali
    "এক": 1, "দুই": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "দশ": 10, "বিশ": 20,
    # Tamil
    "ஒன்று": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5, "பத்து": 10,
    # Telugu
    "ఒకటి": 1, "రెండు": 2, "మూడు": 3, "నాలుగు": 4, "ఐదు": 5, "పది": 10,
    # Kannada
    "ಒಂದು": 1, "ಎರಡು": 2, "ಮೂರು": 3, "ನಾಲ್ಕು": 4, "ಐದು": 5, "ಹತ್ತು": 10,
    # Gujarati
    "એક": 1, "બે": 2, "ત્રણ": 3, "ચાર": 4, "પાંચ": 5, "દસ": 10,
    # Malayalam
    "ഒന്ന്": 1, "രണ്ട്": 2, "മൂന്ന്": 3, "നാല്": 4, "അഞ്ച്": 5, "പത്ത്": 10,
    # Punjabi
    "ਇੱਕ": 1, "ਦੋ": 2, "ਤਿੰਨ": 3, "ਚਾਰ": 4, "ਪੰਜ": 5, "ਦਸ": 10,
}

_WORD_SPLIT_RE = re.compile(r"[^\wऀ-෿]+", re.UNICODE)


def parse_leading_number(text: str) -> float | None:
    """The first quantity in an utterance, whether written as digits or words."""
    digits = _NUM_RE.search(text)
    words = [w for w in _WORD_SPLIT_RE.split(text) if w]

    word_value: float | None = None
    word_index = len(words) + 1
    for i, w in enumerate(words):
        key = w.lower()
        if key in _WORD_NUMBERS:
            word_value = _WORD_NUMBERS[key]
            word_index = i
            break

    if digits and word_value is not None:
        # Whichever comes first in the utterance is the quantity being stated.
        digit_index = len(_WORD_SPLIT_RE.split(text[: digits.start()]))
        return float(digits.group(1)) if digit_index <= word_index else word_value
    if digits:
        return float(digits.group(1))
    return word_value


def extract_amount(text: str, asr_confidence: float, lang: str = "hi") -> SlotExtraction:
    """Parse a spoken amount, and decide whether to trust it.

    Two independent reasons to re-ask, and both are needed:

    * the recogniser was not confident enough;
    * the amount is large enough that a magnitude error would be serious,
      regardless of how confident the recogniser was.

    The second exists because ASR confidence is a statement about acoustics, not
    about consequence. "Ek lakh" and "das lakh" differ by one short syllable and
    by ₹9,00,000.
    """
    value = parse_leading_number(text)
    if value is None:
        return SlotExtraction(
            SlotType.AMOUNT, None, 0.0, True,
            reask_prompt=_reask("amount", lang),
        )
    lowered = text.lower()
    multiplier = 1
    for token, mult in _MAGNITUDE_MULTIPLIERS:
        if token.lower() in lowered:
            multiplier = mult
            break

    paise = rupees(value * multiplier)

    # Ambiguity flag: more than one magnitude word, or a bare number that could
    # be either rupees or lakhs.
    magnitude_hits = sum(1 for token, _ in _MAGNITUDE_MULTIPLIERS if token.lower() in lowered)
    ambiguous = magnitude_hits > 1 or (multiplier == 1 and value <= 100)

    confidence = asr_confidence * (0.6 if ambiguous else 1.0)
    needs_reask = confidence < SLOT_CONFIDENCE_FLOOR or paise >= ALWAYS_CONFIRM_ABOVE_PAISE

    from ..core.money import spoken_inr

    return SlotExtraction(
        slot=SlotType.AMOUNT,
        value=paise,
        confidence=round(confidence, 3),
        needs_reask=needs_reask,
        reask_prompt=_reask("amount", lang) if confidence < SLOT_CONFIDENCE_FLOOR else "",
        read_back=_read_back(spoken_inr(paise, lang).phrase, lang),
    )


def extract_tenure(text: str, asr_confidence: float, lang: str = "hi") -> SlotExtraction:
    parsed = parse_leading_number(text)
    if parsed is None:
        return SlotExtraction(
            SlotType.TENURE_MONTHS, None, 0.0, True, reask_prompt=_reask("tenure", lang)
        )
    months = int(parsed)
    lowered = text.lower()
    if any(w in lowered for w in ("year", "saal", "साल", "वर्ष", "ஆண்டு", "వर్ష", "বছর")):
        months *= 12
    plausible = 3 <= months <= 84
    confidence = asr_confidence * (1.0 if plausible else 0.4)
    return SlotExtraction(
        SlotType.TENURE_MONTHS, months, round(confidence, 3),
        needs_reask=confidence < SLOT_CONFIDENCE_FLOOR,
        reask_prompt=_reask("tenure", lang) if confidence < SLOT_CONFIDENCE_FLOOR else "",
        read_back=_read_back(f"{months} months", lang),
    )


def detect_code_mixing(text: str) -> bool:
    """Code-mixed input is a first-class case, not an error (report §7.5).

    "Mujhe ek lakh ka loan chahiye" is how people actually speak to a bank. A
    pipeline that treats mixed script or mixed vocabulary as a recognition
    failure will re-ask forever and the customer will hang up.
    """
    has_latin = bool(re.search(r"[A-Za-z]{2,}", text))
    has_indic = bool(re.search(r"[ऀ-෿]", text))
    if has_latin and has_indic:
        return True
    romanised = ("chahiye", "kitna", "paisa", "rupaye", "loan", "karna",
                 "mujhe", "hai", "nahi", "kitne", "din", "mahina")
    lowered = text.lower()
    return has_latin and sum(1 for w in romanised if w in lowered) >= 2


_REASK_PROMPTS: dict[str, dict[str, str]] = {
    "en": {
        "amount": "Sorry, how much did you say? Please say the amount again.",
        "tenure": "Over how many months would you like to repay?",
    },
    "hi": {
        "amount": "माफ़ कीजिए, आपने कितनी राशि कही? कृपया दोबारा बताइए।",
        "tenure": "आप कितने महीनों में चुकाना चाहेंगे?",
    },
}

_READ_BACK: dict[str, str] = {
    "en": "I heard {value}. Is that right?",
    "hi": "मैंने {value} सुना। क्या यह सही है?",
}


def _reask(slot: str, lang: str) -> str:
    return _REASK_PROMPTS.get(lang, _REASK_PROMPTS["en"]).get(
        slot, _REASK_PROMPTS["en"][slot]
    )


def _read_back(value: str, lang: str) -> str:
    return _READ_BACK.get(lang, _READ_BACK["en"]).format(value=value)


def is_supported(language: str) -> bool:
    return language in SUPPORTED_LANGUAGES
