"""Money handling for ARTHA.

Two rules, both of which exist because of failure modes named in the report:

1. Money is stored and passed around as **integer paise**. Float rupees drift,
   and a drifting EMI is a compliance incident, not a rounding curiosity. Only
   the Twin's Monte-Carlo interior works in float, and it converts at the
   boundary.

2. Money is rendered with **Indian digit grouping** and lakh/crore vocabulary.
   Report §6.2 ("Vernacular numeracy") requires that cost is never expressed as
   an APR alone; the spoken forms below are what the Key Fact Statement uses.
"""

from __future__ import annotations

from dataclasses import dataclass

PAISE = 100
LAKH = 100_000 * PAISE
CRORE = 100 * LAKH


def rupees(amount: float | int | str) -> int:
    """Convert a rupee quantity to integer paise, rounding half-up."""
    from decimal import ROUND_HALF_UP, Decimal

    d = Decimal(str(amount)) * PAISE
    return int(d.to_integral_value(rounding=ROUND_HALF_UP))


def to_rupees(paise: int) -> float:
    """Convert paise to float rupees. Use only at a display or simulation edge."""
    return paise / PAISE


def indian_group(n: int) -> str:
    """Group digits the Indian way: 1,00,000 rather than 100,000."""
    neg = n < 0
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" + s) if neg else s


def format_inr(paise: int, *, decimals: bool = False) -> str:
    """'₹1,00,000' — the canonical written form used across every surface."""
    whole, frac = divmod(abs(paise), PAISE)
    sign = "-" if paise < 0 else ""
    body = indian_group(whole)
    if decimals:
        body = f"{body}.{frac:02d}"
    return f"{sign}₹{body}"


@dataclass(frozen=True)
class SpokenAmount:
    """An amount decomposed for speech synthesis.

    The assistant reads ``phrase``; ``magnitude`` and ``value`` are retained so
    the AI Firewall's numeric-grounding check (report §7.7) can verify that
    every numeral the model utters traces back to a Decision Object field.
    """

    paise: int
    value: float
    magnitude: str          # "" | "hazaar" | "lakh" | "crore"
    phrase: str


def spoken_inr(paise: int, lang: str = "en") -> SpokenAmount:
    """Render an amount the way a person actually says it.

    ₹1,00,000 is spoken as "one lakh", not "one hundred thousand". Getting this
    wrong is not cosmetic: report §6.2 identifies a ₹1,00,000 request misheard
    as ₹10,00,000 as an unacceptable failure mode, and the same vocabulary gap
    that breaks recognition breaks comprehension on the way back out.
    """
    words = _MAGNITUDE_WORDS.get(lang, _MAGNITUDE_WORDS["en"])
    a = abs(paise)

    if a >= CRORE:
        value, magnitude = a / CRORE, words["crore"]
    elif a >= LAKH:
        value, magnitude = a / LAKH, words["lakh"]
    elif a >= 1000 * PAISE:
        value, magnitude = a / (1000 * PAISE), words["thousand"]
    else:
        value, magnitude = a / PAISE, ""

    # One decimal place, but only when it carries information: "2.5 lakh" is
    # useful, "2.0 lakh" sounds like a machine reading a field.
    if abs(value - round(value)) < 0.05:
        num = str(int(round(value)))
    else:
        num = f"{value:.1f}"

    currency = words["rupees"]
    phrase = f"{num} {magnitude} {currency}".replace("  ", " ").strip()
    if paise < 0:
        phrase = f"{words['minus']} {phrase}"
    return SpokenAmount(paise=paise, value=value, magnitude=magnitude, phrase=phrase)


_MAGNITUDE_WORDS: dict[str, dict[str, str]] = {
    "en": {"thousand": "thousand", "lakh": "lakh", "crore": "crore",
           "rupees": "rupees", "minus": "minus"},
    "hi": {"thousand": "हज़ार", "lakh": "लाख", "crore": "करोड़",
           "rupees": "रुपये", "minus": "ऋण"},
    "mr": {"thousand": "हजार", "lakh": "लाख", "crore": "कोटी",
           "rupees": "रुपये", "minus": "वजा"},
    "bn": {"thousand": "হাজার", "lakh": "লাখ", "crore": "কোটি",
           "rupees": "টাকা", "minus": "বিয়োগ"},
    "ta": {"thousand": "ஆயிரம்", "lakh": "லட்சம்", "crore": "கோடி",
           "rupees": "ரூபாய்", "minus": "கழித்தல்"},
    "te": {"thousand": "వేలు", "lakh": "లక్ష", "crore": "కోటి",
           "rupees": "రూపాయలు", "minus": "మైనస్"},
    "kn": {"thousand": "ಸಾವಿರ", "lakh": "ಲಕ್ಷ", "crore": "ಕೋಟಿ",
           "rupees": "ರೂಪಾಯಿ", "minus": "ಮೈನಸ್"},
    "gu": {"thousand": "હજાર", "lakh": "લાખ", "crore": "કરોડ",
           "rupees": "રૂપિયા", "minus": "ઓછા"},
    "ml": {"thousand": "ആയിരം", "lakh": "ലക്ഷം", "crore": "കോടി",
           "rupees": "രൂപ", "minus": "മൈനസ്"},
    "pa": {"thousand": "ਹਜ਼ਾਰ", "lakh": "ਲੱਖ", "crore": "ਕਰੋੜ",
           "rupees": "ਰੁਪਏ", "minus": "ਘਟਾਓ"},
    "or": {"thousand": "ହଜାର", "lakh": "ଲକ୍ଷ", "crore": "କୋଟି",
           "rupees": "ଟଙ୍କା", "minus": "ବିଯୋଗ"},
    "as": {"thousand": "হাজাৰ", "lakh": "লাখ", "crore": "কোটি",
           "rupees": "টকা", "minus": "বিয়োগ"},
}

SUPPORTED_LANGUAGES = tuple(_MAGNITUDE_WORDS.keys())


def emi_paise(principal_paise: int, annual_rate: float, tenure_months: int) -> int:
    """Standard reducing-balance EMI, returned in integer paise.

    ``annual_rate`` is a fraction (0.14 == 14% p.a.).
    """
    if tenure_months <= 0:
        raise ValueError("tenure_months must be positive")
    if principal_paise <= 0:
        return 0
    r = annual_rate / 12.0
    if r <= 0:
        return -(-principal_paise // tenure_months)      # ceil division
    factor = (1 + r) ** tenure_months
    emi = principal_paise * r * factor / (factor - 1)
    return int(round(emi))


def total_cost_paise(emi: int, tenure_months: int, principal_paise: int) -> int:
    """Interest paid over the life of the loan — the number the KFS must speak.

    Report §6.2: a longer tenure lowers the monthly payment but raises the total
    cost, and the customer is told the second half of that sentence before
    consent, not after.
    """
    return emi * tenure_months - principal_paise
