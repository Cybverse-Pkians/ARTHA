"""The Key Fact Statement, spoken.

Report §6.2: a Key Fact Statement is generated in the customer's language and
**read aloud before consent**, including the honest trade-off that a longer
tenure lowers the monthly payment but raises the total cost.

Report §9.3 makes the second half non-negotiable: tenure extension is never
presented as a pure benefit. So :func:`build_kfs` computes the additional total
cost of every longer alternative it shows, and the comparison table always
carries that column. There is no code path that renders a longer tenure without
its price.

Cost is never expressed as an annual percentage rate alone. It is rendered as
"₹4,050 every month for 30 months — ₹21,500 more than you borrow", because that
is the sentence a first-time borrower can actually act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.money import emi_paise, format_inr, spoken_inr, total_cost_paise
from ..products.catalogue import Product, ProductOffer

REGULATORY_NOTE = (
    "Key Fact Statement content and format must be verified against the current "
    "RBI Digital Lending Directions before any live use (report §11.2)."
)


@dataclass(frozen=True)
class KFSLine:
    key: str
    label: str
    value: str
    spoken: str


@dataclass(frozen=True)
class TenureOption:
    tenure_months: int
    emi_paise: int
    total_interest_paise: int
    additional_cost_vs_shortest_paise: int
    is_recommended: bool

    @property
    def is_longer_and_dearer(self) -> bool:
        return self.additional_cost_vs_shortest_paise > 0


@dataclass(frozen=True)
class KeyFactStatement:
    language: str
    product_name: str
    lines: tuple[KFSLine, ...]
    tenure_options: tuple[TenureOption, ...]
    spoken_script: str
    cooling_off_note: str
    grievance_note: str
    regulatory_note: str = REGULATORY_NOTE
    numeric_ground: tuple[float, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "language": self.language,
            "product_name": self.product_name,
            "lines": [
                {"key": l.key, "label": l.label, "value": l.value, "spoken": l.spoken}
                for l in self.lines
            ],
            "tenure_options": [
                {
                    "tenure_months": t.tenure_months,
                    "emi": format_inr(t.emi_paise),
                    "emi_paise": t.emi_paise,
                    "total_interest": format_inr(t.total_interest_paise),
                    "additional_cost": format_inr(t.additional_cost_vs_shortest_paise),
                    "additional_cost_paise": t.additional_cost_vs_shortest_paise,
                    "recommended": t.is_recommended,
                }
                for t in self.tenure_options
            ],
            "spoken_script": self.spoken_script,
            "cooling_off": self.cooling_off_note,
            "grievance": self.grievance_note,
            "regulatory_note": self.regulatory_note,
        }


_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "amount": "Amount you receive",
        "rate": "Interest rate",
        "tenure": "You repay over",
        "emi": "Every month",
        "total_interest": "Extra you pay in total",
        "total_repayable": "Total you repay",
        "due_day": "Payment date",
        "fees": "Fees and charges",
        "prepayment": "Paying off early",
    },
    "hi": {
        "amount": "आपको मिलने वाली राशि",
        "rate": "ब्याज दर",
        "tenure": "चुकाने की अवधि",
        "emi": "हर महीने",
        "total_interest": "कुल अतिरिक्त भुगतान",
        "total_repayable": "कुल चुकाई जाने वाली राशि",
        "due_day": "भुगतान की तारीख",
        "fees": "शुल्क",
        "prepayment": "समय से पहले चुकाना",
    },
    "mr": {
        "amount": "तुम्हाला मिळणारी रक्कम",
        "rate": "व्याजदर",
        "tenure": "परतफेडीची मुदत",
        "emi": "दर महिना",
        "total_interest": "एकूण जादा भरणा",
        "total_repayable": "एकूण परतफेड",
        "due_day": "भरण्याची तारीख",
        "fees": "शुल्क",
        "prepayment": "मुदतीआधी फेडणे",
    },
    "ta": {
        "amount": "உங்களுக்குக் கிடைக்கும் தொகை",
        "rate": "வட்டி விகிதம்",
        "tenure": "திருப்பிச் செலுத்தும் காலம்",
        "emi": "மாதந்தோறும்",
        "total_interest": "மொத்தத்தில் கூடுதலாகச் செலுத்துவது",
        "total_repayable": "மொத்தத் திருப்பிச் செலுத்தல்",
        "due_day": "செலுத்தும் தேதி",
        "fees": "கட்டணங்கள்",
        "prepayment": "முன்கூட்டியே அடைப்பது",
    },
    "bn": {
        "amount": "আপনি যে টাকা পাবেন",
        "rate": "সুদের হার",
        "tenure": "শোধের মেয়াদ",
        "emi": "প্রতি মাসে",
        "total_interest": "মোট অতিরিক্ত পরিশোধ",
        "total_repayable": "মোট শোধ",
        "due_day": "পরিশোধের তারিখ",
        "fees": "ফি ও চার্জ",
        "prepayment": "আগেভাগে শোধ",
    },
}

_SCRIPT: dict[str, str] = {
    "en": (
        "You will receive {amount}. You will pay {emi} every month for {tenure} months, "
        "on the {day} of each month. In total you will pay back {total_repayable}, which is "
        "{total_interest} more than you borrow. {tenure_warning} "
        "There are no hidden charges. You can cancel within the cooling-off period "
        "without penalty. Shall I read that again?"
    ),
    "hi": (
        "आपको {amount} मिलेंगे। आप हर महीने की {day} तारीख को {emi} देंगे, {tenure} महीनों तक। "
        "कुल मिलाकर आप {total_repayable} चुकाएंगे, जो आपकी ली गई राशि से {total_interest} अधिक है। "
        "{tenure_warning} कोई छिपा हुआ शुल्क नहीं है। आप कूलिंग-ऑफ़ अवधि में बिना जुर्माने के "
        "रद्द कर सकते हैं। क्या मैं दोबारा पढ़ूँ?"
    ),
    "mr": (
        "तुम्हाला {amount} मिळतील. तुम्ही दर महिन्याच्या {day} तारखेला {emi} भराल, {tenure} "
        "महिने. एकूण तुम्ही {total_repayable} परत कराल, जे तुम्ही घेतलेल्या रकमेपेक्षा "
        "{total_interest} जास्त आहे. {tenure_warning} कोणतेही छुपे शुल्क नाही. कूलिंग-ऑफ "
        "कालावधीत तुम्ही दंडाशिवाय रद्द करू शकता. मी पुन्हा वाचून दाखवू का?"
    ),
    "ta": (
        "உங்களுக்கு {amount} கிடைக்கும். ஒவ்வொரு மாதமும் {day}-ஆம் தேதி {emi} "
        "செலுத்துவீர்கள், {tenure} மாதங்களுக்கு. மொத்தம் {total_repayable} திருப்பிச் "
        "செலுத்துவீர்கள், அது நீங்கள் வாங்கியதை விட {total_interest} அதிகம். "
        "{tenure_warning} மறைமுகக் கட்டணங்கள் எதுவும் இல்லை. கூலிங்-ஆஃப் காலத்தில் "
        "அபராதம் இன்றி ரத்து செய்யலாம். மீண்டும் படிக்கட்டுமா?"
    ),
    "bn": (
        "আপনি {amount} পাবেন। প্রতি মাসের {day} তারিখে {emi} দেবেন, {tenure} মাস ধরে। "
        "মোট আপনি {total_repayable} শোধ করবেন, যা আপনার নেওয়া টাকার চেয়ে "
        "{total_interest} বেশি। {tenure_warning} কোনো লুকানো চার্জ নেই। কুলিং-অফ "
        "সময়ের মধ্যে জরিমানা ছাড়াই বাতিল করতে পারেন। আবার পড়ে শোনাব?"
    ),
}

_TENURE_WARNING: dict[str, str] = {
    "en": (
        "A longer tenure would lower the monthly payment to {alt_emi}, but you would "
        "pay {alt_extra} more overall."
    ),
    "hi": (
        "लंबी अवधि लेने पर मासिक किस्त {alt_emi} हो जाएगी, लेकिन कुल मिलाकर आप "
        "{alt_extra} अधिक चुकाएंगे।"
    ),
    "mr": (
        "जास्त मुदत घेतल्यास मासिक हप्ता {alt_emi} होईल, पण एकूण तुम्ही {alt_extra} "
        "जास्त भराल."
    ),
    "ta": (
        "நீண்ட காலம் எடுத்தால் மாதத் தவணை {alt_emi} ஆகும், ஆனால் மொத்தத்தில் "
        "{alt_extra} அதிகம் செலுத்துவீர்கள்."
    ),
    "bn": (
        "মেয়াদ বাড়ালে মাসিক কিস্তি {alt_emi} হবে, তবে মোট আপনি {alt_extra} বেশি দেবেন।"
    ),
}

_COOLING_OFF: dict[str, str] = {
    "en": (
        "You may exit this loan during the cooling-off period by repaying the principal "
        "and the proportionate cost, without any penalty."
    ),
    "hi": (
        "कूलिंग-ऑफ़ अवधि के दौरान आप मूल राशि और आनुपातिक लागत चुकाकर, बिना किसी "
        "जुर्माने के इस ऋण से बाहर निकल सकते हैं।"
    ),
    "mr": (
        "कूलिंग-ऑफ कालावधीत तुम्ही मुद्दल आणि प्रमाणशीर खर्च भरून, कोणत्याही दंडाशिवाय "
        "या कर्जातून बाहेर पडू शकता."
    ),
    "ta": (
        "கூலிங்-ஆஃப் காலத்தில் அசலையும் விகிதாசாரச் செலவையும் செலுத்தி, அபராதம் "
        "இன்றி இந்தக் கடனிலிருந்து வெளியேறலாம்."
    ),
    "bn": (
        "কুলিং-অফ সময়ের মধ্যে আসল ও আনুপাতিক খরচ দিয়ে, কোনো জরিমানা ছাড়াই এই ঋণ "
        "থেকে বেরিয়ে আসতে পারেন।"
    ),
}

_GRIEVANCE: dict[str, str] = {
    "en": "If you disagree with this decision, say so and a person will review it.",
    "hi": "यदि आप इस निर्णय से असहमत हैं, तो बताइए — एक व्यक्ति इसकी समीक्षा करेगा।",
    "mr": "तुम्ही या निर्णयाशी असहमत असाल तर सांगा — एक व्यक्ती त्याची तपासणी करेल.",
    "ta": "இந்த முடிவை ஏற்கவில்லை என்றால் சொல்லுங்கள் — ஒருவர் அதைப் பரிசீலிப்பார்.",
    "bn": "এই সিদ্ধান্তে একমত না হলে বলুন — একজন মানুষ এটি পর্যালোচনা করবেন।",
}


def build_kfs(
    offer: ProductOffer,
    *,
    lang: str = "hi",
    fees_paise: int = 0,
) -> KeyFactStatement:
    """Build the Key Fact Statement for a structured offer."""
    labels = _LABELS.get(lang, _LABELS["en"])
    product: Product = offer.product

    total_repayable = offer.emi_paise * offer.tenure_months
    options = _tenure_options(product, offer)

    # The cheapest-monthly alternative is what a customer would otherwise be
    # steered toward, so that is the one whose true cost gets spoken.
    longer = [t for t in options if t.tenure_months > offer.tenure_months]
    if longer:
        alt = min(longer, key=lambda t: t.emi_paise)
        warning = _TENURE_WARNING.get(lang, _TENURE_WARNING["en"]).format(
            alt_emi=format_inr(alt.emi_paise),
            alt_extra=format_inr(alt.additional_cost_vs_shortest_paise),
        )
    else:
        warning = ""

    lines = (
        KFSLine("amount", labels["amount"], format_inr(offer.amount_paise),
                spoken_inr(offer.amount_paise, lang).phrase),
        KFSLine("rate", labels["rate"], f"{offer.annual_rate:.2%} p.a.",
                f"{offer.annual_rate * 100:.2f} percent a year"),
        KFSLine("tenure", labels["tenure"], f"{offer.tenure_months} months",
                f"{offer.tenure_months} months"),
        KFSLine("emi", labels["emi"], format_inr(offer.emi_paise),
                spoken_inr(offer.emi_paise, lang).phrase),
        KFSLine("total_interest", labels["total_interest"],
                format_inr(offer.total_interest_paise),
                spoken_inr(offer.total_interest_paise, lang).phrase),
        KFSLine("total_repayable", labels["total_repayable"], format_inr(total_repayable),
                spoken_inr(total_repayable, lang).phrase),
        KFSLine("due_day", labels["due_day"], f"{offer.day_of_month} of each month",
                f"the {offer.day_of_month}"),
        KFSLine("fees", labels["fees"], format_inr(fees_paise) if fees_paise else "None",
                spoken_inr(fees_paise, lang).phrase if fees_paise else "none"),
        KFSLine("prepayment", labels["prepayment"], "Allowed without penalty",
                "allowed without penalty"),
    )

    script = _SCRIPT.get(lang, _SCRIPT["en"]).format(
        amount=format_inr(offer.amount_paise),
        emi=format_inr(offer.emi_paise),
        tenure=offer.tenure_months,
        day=offer.day_of_month,
        total_repayable=format_inr(total_repayable),
        total_interest=format_inr(offer.total_interest_paise),
        tenure_warning=warning,
    ).replace("  ", " ")

    ground: list[float] = [
        offer.amount_paise, offer.emi_paise, offer.total_interest_paise,
        total_repayable, offer.tenure_months, offer.day_of_month,
        round(offer.annual_rate * 100, 2), fees_paise,
    ]
    for t in options:
        ground.extend([t.emi_paise, t.total_interest_paise,
                       t.additional_cost_vs_shortest_paise, t.tenure_months])
    ground.extend([v / 100.0 for v in list(ground) if abs(v) >= 100])

    return KeyFactStatement(
        language=lang,
        product_name=product.name,
        lines=lines,
        tenure_options=options,
        spoken_script=script,
        cooling_off_note=_COOLING_OFF.get(lang, _COOLING_OFF["en"]),
        grievance_note=_GRIEVANCE.get(lang, _GRIEVANCE["en"]),
        numeric_ground=tuple(sorted(set(float(v) for v in ground))),
    )


def _tenure_options(product: Product, offer: ProductOffer) -> tuple[TenureOption, ...]:
    """Every tenure the product allows, each priced honestly.

    The baseline for "additional cost" is the shortest tenure shown, so the
    figure answers the question a customer actually asks — *what does it cost me
    to make the monthly payment smaller?*
    """
    if product.annual_rate <= 0:
        return ()

    priced = []
    for tenure in sorted(product.tenures):
        emi = emi_paise(offer.amount_paise, product.annual_rate, tenure)
        interest = total_cost_paise(emi, tenure, offer.amount_paise)
        priced.append((tenure, emi, interest))

    if not priced:
        return ()
    baseline_interest = priced[0][2]

    return tuple(
        TenureOption(
            tenure_months=tenure,
            emi_paise=emi,
            total_interest_paise=interest,
            additional_cost_vs_shortest_paise=max(interest - baseline_interest, 0),
            is_recommended=(tenure == offer.tenure_months),
        )
        for tenure, emi, interest in priced
    )
