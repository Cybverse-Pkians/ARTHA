"""Reason-code registry.

Report §7.6 requires one artefact rendered two ways: a regulator-grade trace and
a single spoken sentence, both derived from the same source so they cannot
drift. A reason code is that shared unit — it carries a supervisory description
*and* a customer-facing template, side by side in one record, so that adding a
reason without deciding how to say it out loud is impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Polarity(str, Enum):
    FAVOURABLE = "FAVOURABLE"
    ADVERSE = "ADVERSE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ReasonCodeSpec:
    code: str
    title: str                                  # regulator rendering
    description: str
    polarity: Polarity
    templates: dict[str, str] = field(default_factory=dict)   # customer rendering
    adverse_action: bool = False                # requires human review (§9.6)

    def say(self, lang: str = "en", **kwargs: object) -> str:
        template = self.templates.get(lang) or self.templates.get("en") or self.title
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            # A malformed substitution must never surface a raw brace to a
            # customer; fall back to the language-neutral title.
            return self.title


_R: dict[str, ReasonCodeSpec] = {}


def _reg(spec: ReasonCodeSpec) -> ReasonCodeSpec:
    _R[spec.code] = spec
    return spec


def get(code: str) -> ReasonCodeSpec:
    return _R[code]


def all_codes() -> dict[str, ReasonCodeSpec]:
    return dict(_R)


# --- Affordability, from the Financial Twin (§5.1) --------------------------

AFF_BUFFER_BREACH = _reg(ReasonCodeSpec(
    code="AFF-001",
    title="Projected balance breaches minimum safe buffer within the horizon",
    description=(
        "The Twin's six-month simulation projects the customer's balance falling "
        "below the configured safe buffer on at least one path above the "
        "breach-probability ceiling, with the candidate obligation applied."
    ),
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "Not right now — with this EMI your balance would fall below your safety buffer around {month}.",
        "hi": "अभी नहीं — इस EMI के साथ {month} के आसपास आपका बैलेंस आपके सुरक्षा बफ़र से नीचे चला जाएगा।",
        "mr": "आत्ता नाही — या हप्त्यासह {month} च्या सुमारास तुमची शिल्लक सुरक्षा राखीवाच्या खाली जाईल.",
        "ta": "இப்போது வேண்டாம் — இந்தத் தவணையுடன் {month} வாக்கில் உங்கள் இருப்பு பாதுகாப்பு நிலைக்குக் கீழே செல்லும்.",
        "bn": "এখন নয় — এই কিস্তির সঙ্গে {month} নাগাদ আপনার ব্যালান্স নিরাপত্তা সঞ্চয়ের নিচে নেমে যাবে।",
    },
))

AFF_HEADROOM_OK = _reg(ReasonCodeSpec(
    code="AFF-002",
    title="Affordability cleared with retained buffer",
    description="Projected balance stays above the safe buffer on all stress scenarios tested.",
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "Your balance stays above your safety buffer every month, even if your income is late.",
        "hi": "आपकी आमदनी देर से आने पर भी हर महीने आपका बैलेंस सुरक्षा बफ़र से ऊपर रहता है।",
        "mr": "तुमचे उत्पन्न उशिरा आले तरी दर महिन्याला तुमची शिल्लक सुरक्षा राखीवाच्या वर राहते.",
        "ta": "உங்கள் வருமானம் தாமதமானாலும், ஒவ்வொரு மாதமும் உங்கள் இருப்பு பாதுகாப்பு நிலைக்கு மேலே இருக்கும்.",
        "bn": "আপনার আয় দেরিতে এলেও প্রতি মাসে আপনার ব্যালান্স নিরাপত্তা সঞ্চয়ের উপরে থাকে।",
    },
))

AFF_SHOCK_FRAGILE = _reg(ReasonCodeSpec(
    code="AFF-003",
    title="Affordability cleared in base case but fails a tested shock scenario",
    description="Base path clears; the delayed-income or medical-shock scenario breaches the buffer.",
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "You can absorb one {shock}, but not two — so this amount is more than we would recommend.",
        "hi": "आप एक {shock} संभाल सकते हैं, दो नहीं — इसलिए यह राशि हमारी सलाह से अधिक है।",
        "mr": "तुम्ही एक {shock} पेलू शकता, दोन नाही — म्हणून ही रक्कम आम्ही सुचवण्यापेक्षा जास्त आहे.",
        "ta": "ஒரு {shock}-ஐ உங்களால் தாங்க முடியும், இரண்டை அல்ல — எனவே இந்தத் தொகை நாங்கள் பரிந்துரைப்பதை விட அதிகம்.",
        "bn": "আপনি একটি {shock} সামলাতে পারেন, দুটি নয় — তাই এই অঙ্ক আমাদের সুপারিশের চেয়ে বেশি।",
    },
))

AFF_OTI_CEILING = _reg(ReasonCodeSpec(
    code="AFF-004",
    title="Obligation-to-income ratio exceeds policy ceiling",
    description="Existing plus proposed EMI exceeds the configured share of assessed monthly income.",
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "Your existing EMIs already take up {oti} of your monthly income.",
        "hi": "आपकी मौजूदा EMI पहले से ही आपकी मासिक आय का {oti} ले रही हैं।",
        "mr": "तुमचे सध्याचे हप्तेच तुमच्या मासिक उत्पन्नाच्या {oti} घेतात.",
        "ta": "உங்கள் தற்போதைய தவணைகளே உங்கள் மாத வருமானத்தில் {oti} எடுத்துக்கொள்கின்றன.",
        "bn": "আপনার বর্তমান কিস্তিগুলিই আপনার মাসিক আয়ের {oti} নিয়ে নেয়।",
    },
))

# --- Eligibility (§5.2 step 1) ---------------------------------------------

ELG_HARD_RULE = _reg(ReasonCodeSpec(
    code="ELG-001",
    title="Hard eligibility rule not satisfied",
    description="A deterministic product policy rule (age, KYC, residency, minimum tenure) failed.",
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={
        "en": "This product has a requirement you do not meet yet: {rule}.",
        "hi": "इस उत्पाद की एक शर्त अभी पूरी नहीं होती: {rule}।",
        "mr": "या उत्पादनाची एक अट तुम्ही अजून पूर्ण करत नाही: {rule}.",
        "ta": "இந்தத் தயாரிப்பின் ஒரு நிபந்தனையை நீங்கள் இன்னும் பூர்த்தி செய்யவில்லை: {rule}.",
        "bn": "এই পণ্যের একটি শর্ত আপনি এখনও পূরণ করেন না: {rule}।",
    },
))

ELG_THIN_FILE_ALT_DATA = _reg(ReasonCodeSpec(
    code="ELG-002",
    title="Thin bureau file; assessed on ethically bounded alternate data",
    description=(
        "No usable bureau history. Assessment used utility payments, UPI rent, "
        "recharge regularity and SHG repayment records only (report §9.5)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "You do not have a credit history yet, so we looked at your bill and rent payments instead.",
        "hi": "आपका क्रेडिट इतिहास नहीं है, इसलिए हमने आपके बिल और किराए के भुगतान देखे।",
        "mr": "तुमचा पतइतिहास अजून नाही, म्हणून आम्ही तुमची बिले आणि भाडे भरणा पाहिली.",
        "ta": "உங்களுக்கு இன்னும் கடன் வரலாறு இல்லை, எனவே உங்கள் கட்டணங்களையும் வாடகைச் செலுத்தல்களையும் பார்த்தோம்.",
        "bn": "আপনার এখনও ঋণের ইতিহাস নেই, তাই আমরা আপনার বিল ও ভাড়ার পেমেন্ট দেখেছি।",
    },
))

# --- Recovery Mode (§6.5) ---------------------------------------------------

REC_STRESS_SUPPRESSION = _reg(ReasonCodeSpec(
    code="REC-001",
    title="Customer in Recovery Mode; all selling suppressed",
    description=(
        "Recovery-Mode state is AT_RISK or RECOVERY. No product in any family is "
        "rendered. This is the defining safeguard of the system (report §9.3)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "We are not offering you anything new while we help you get through this month.",
        "hi": "इस महीने आपकी मदद करते समय हम आपको कुछ नया नहीं दे रहे हैं।",
        "mr": "हा महिना पार करायला मदत करत असताना आम्ही तुम्हाला काहीही नवीन देत नाही.",
        "ta": "இந்த மாதத்தைக் கடக்க உதவும்போது உங்களுக்குப் புதிதாக எதையும் வழங்கவில்லை.",
        "bn": "এই মাসটা পার করতে সাহায্য করার সময় আমরা আপনাকে নতুন কিছু দিচ্ছি না।",
    },
))

REC_WATCH_PAUSE = _reg(ReasonCodeSpec(
    code="REC-002",
    title="Customer in WATCH; new credit paused without contact",
    description="Early stress indicators present. New credit offers paused; customer not contacted.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "We are keeping an eye on things and have paused new credit offers for now.", "hi": "हम स्थिति पर नज़र रखे हुए हैं और फ़िलहाल नए ऋण प्रस्ताव रोक दिए हैं।", "mr": "आम्ही परिस्थितीवर लक्ष ठेवून आहोत आणि सध्या नवीन कर्ज प्रस्ताव थांबवले आहेत.", "ta": "நிலைமையை நாங்கள் கவனித்து வருகிறோம், தற்போது புதிய கடன் வழங்கல்களை நிறுத்தியுள்ளோம்.", "bn": "আমরা পরিস্থিতির দিকে নজর রাখছি এবং আপাতত নতুন ঋণের প্রস্তাব থামিয়ে রেখেছি।"},
))

# --- Conduct controls (§9.3) ------------------------------------------------

NDG_BUDGET_EXHAUSTED = _reg(ReasonCodeSpec(
    code="NDG-001",
    title="Monthly nudge budget exhausted",
    description="Contact frequency cap reached for the current calendar month.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "We have already contacted you enough this month.", "hi": "इस महीने हम आपसे पर्याप्त बार संपर्क कर चुके हैं।", "mr": "या महिन्यात आम्ही तुमच्याशी पुरेसा संपर्क साधला आहे.", "ta": "இந்த மாதம் உங்களைப் போதுமான அளவு தொடர்புகொண்டுவிட்டோம்.", "bn": "এই মাসে আমরা আপনার সঙ্গে যথেষ্ট যোগাযোগ করেছি।"},
))

NDG_PRODUCT_COOLDOWN = _reg(ReasonCodeSpec(
    code="NDG-002",
    title="Per-product cooldown active",
    description="This product family was offered within the configured cooldown window.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "We showed you this recently and will not ask again so soon.", "hi": "हमने यह हाल ही में दिखाया था और इतनी जल्दी दोबारा नहीं पूछेंगे।", "mr": "आम्ही हे नुकतेच दाखवले होते आणि इतक्या लवकर पुन्हा विचारणार नाही.", "ta": "இதை சமீபத்தில் காட்டினோம், இவ்வளவு விரைவில் மீண்டும் கேட்க மாட்டோம்.", "bn": "আমরা এটি সম্প্রতি দেখিয়েছি এবং এত তাড়াতাড়ি আবার জিজ্ঞেস করব না।"},
))

NDG_DO_NOT_ASK = _reg(ReasonCodeSpec(
    code="NDG-003",
    title="Customer exercised 'do not ask me about this again'",
    description="An honoured standing preference suppresses this product family indefinitely.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "You asked us not to bring this up again.", "hi": "आपने हमसे कहा था कि यह बात दोबारा न उठाएँ।", "mr": "तुम्ही आम्हाला हा विषय पुन्हा काढू नका असे सांगितले होते.", "ta": "இதை மீண்டும் எழுப்ப வேண்டாம் என்று நீங்கள் சொல்லியிருந்தீர்கள்.", "bn": "আপনি আমাদের বলেছিলেন এই বিষয়টি আর না তুলতে।"},
))

EMP_CALENDAR = _reg(ReasonCodeSpec(
    code="EMP-001",
    title="Empathy calendar suppression active",
    description="Detected bereavement, job loss or examination season suppresses offers.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "This is not a good time to be asking you about a financial product.", "hi": "यह आपसे किसी वित्तीय उत्पाद के बारे में पूछने का सही समय नहीं है।", "mr": "तुम्हाला आर्थिक उत्पादनाबद्दल विचारण्याची ही योग्य वेळ नाही.", "ta": "நிதித் தயாரிப்பு குறித்து உங்களிடம் கேட்க இது சரியான நேரம் அல்ல.", "bn": "আর্থিক পণ্য নিয়ে আপনাকে জিজ্ঞেস করার এটি সঠিক সময় নয়।"},
))

# --- Fairness (§9.5) --------------------------------------------------------

FAI_COHORT_DRIFT = _reg(ReasonCodeSpec(
    code="FAI-001",
    title="Cohort benefit distribution outside tolerance; decision held for review",
    description=(
        "The favourable-offer rate for this customer's fairness slice diverged from "
        "the reference population beyond tolerance. Routed to human review."
    ),
    polarity=Polarity.NEUTRAL,
    adverse_action=True,
    templates={"en": "We are having a person check this before we come back to you.", "hi": "हम इसे आगे बढ़ाने से पहले एक व्यक्ति से इसकी जाँच करा रहे हैं।", "mr": "पुढे जाण्यापूर्वी आम्ही एका व्यक्तीकडून याची तपासणी करून घेत आहोत.", "ta": "தொடர்வதற்கு முன் ஒருவரிடம் இதைச் சரிபார்க்கிறோம்.", "bn": "এগোনোর আগে আমরা একজন মানুষকে দিয়ে এটি যাচাই করাচ্ছি।"},
))

# --- Moment detection (§6.1) ------------------------------------------------

MOM_NO_TRIGGER = _reg(ReasonCodeSpec(
    code="MOM-001",
    title="No material change detected; silence is the correct output",
    description="The Moment Engine found no qualifying trigger. Not an error state.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "Nothing has changed that we need to talk to you about.", "hi": "आज बताने लायक कुछ नहीं है।", "mr": "आज सांगण्यासारखे काही नाही.", "ta": "இன்று சொல்ல ஒன்றுமில்லை.", "bn": "আজ বলার মতো কিছু নেই।"},
))

MOM_CUSTOMER_REQUEST = _reg(ReasonCodeSpec(
    code="MOM-008",
    title="Customer asked for a specific amount",
    description=(
        "The moment was supplied by the customer rather than detected by the "
        "Moment Engine. Recorded distinctly because an answer to a question the "
        "customer asked and an offer the bank initiated are different conduct "
        "events even when the product is the same."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "You asked us about this, so we checked it against your cash flow.",
        "hi": "आपने इसके बारे में पूछा, इसलिए हमने इसे आपके नकदी प्रवाह पर जाँचा।",
        "mr": "तुम्ही याबद्दल विचारले, म्हणून आम्ही ते तुमच्या रोख प्रवाहावर तपासले.",
        "ta": "நீங்கள் இதைப் பற்றிக் கேட்டீர்கள், எனவே உங்கள் பணப்புழக்கத்தில் சரிபார்த்தோம்.",
        "bn": "আপনি এ বিষয়ে জিজ্ঞেস করেছেন, তাই আমরা তা আপনার নগদ প্রবাহে যাচাই করেছি।",
    },
))

MOM_EMI_ENDING = _reg(ReasonCodeSpec(
    code="MOM-002",
    title="Existing obligation ends within trigger window",
    description="A detected EMI series terminates within 60 days, freeing committed outflow.",
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "Your {label} finishes in {days} days, which frees up {amount} a month.",
        "hi": "आपका {label} {days} दिनों में पूरा हो रहा है, जिससे हर महीने {amount} बच जाएंगे।",
        "mr": "तुमचा {label} {days} दिवसांत संपतो, त्यामुळे दर महिन्याला {amount} मोकळे होतात.",
        "ta": "உங்கள் {label} {days} நாட்களில் முடிகிறது, இதனால் மாதம் {amount} விடுபடும்.",
        "bn": "আপনার {label} {days} দিনে শেষ হচ্ছে, ফলে প্রতি মাসে {amount} মুক্ত হবে।",
    },
))

MOM_HIGH_COST_OUTFLOW = _reg(ReasonCodeSpec(
    code="MOM-003",
    title="Outflow detected to a high-interest lending application",
    description="Repeated debits to a counterparty classified as a high-cost lender.",
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "You are paying {rate} elsewhere. We can offer the same amount at {our_rate}.",
        "hi": "आप कहीं और {rate} दे रहे हैं। हम वही राशि {our_rate} पर दे सकते हैं।",
        "mr": "अ‍ॅप कर्जदाते {rate} आकारतात. आमचा दर {our_rate} आहे.",
        "ta": "செயலி கடன் வழங்குநர்கள் {rate} வசூலிக்கிறார்கள். எங்கள் வட்டி {our_rate}.",
        "bn": "অ্যাপ ঋণদাতারা {rate} নেয়। আমাদের সুদ {our_rate}।",
    },
))

MOM_INCOME_RISE = _reg(ReasonCodeSpec(
    code="MOM-004",
    title="Sustained income increase detected with healthy buffer",
    description="Salary series changepoint upward, sustained three cycles, buffer already adequate.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "Your income went up and your buffer is healthy — this is a good moment to save more.", "hi": "आपकी आमदनी लगातार बढ़ी है।", "mr": "तुमचे उत्पन्न सातत्याने वाढले आहे.", "ta": "உங்கள் வருமானம் தொடர்ச்சியாக அதிகரித்துள்ளது.", "bn": "আপনার আয় ধারাবাহিকভাবে বেড়েছে।"},
))

MOM_PROTECTION_GAP = _reg(ReasonCodeSpec(
    code="MOM-005",
    title="Protection gap detected against observed obligations",
    description="Dependants and obligations present with no detected cover of the relevant type.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "You support {dependants} people and have no cover for them.", "hi": "आप पर निर्भर {dependants} लोग हैं और कोई बीमा कवर दर्ज नहीं है।", "mr": "तुमच्यावर {dependants} जण अवलंबून आहेत आणि कोणतेही विमा संरक्षण नोंदलेले नाही.", "ta": "உங்களை நம்பி {dependants} பேர் உள்ளனர், காப்பீட்டுப் பாதுகாப்பு எதுவும் பதிவாகவில்லை.", "bn": "আপনার উপর {dependants} জন নির্ভরশীল এবং তাঁদের জন্য কোনো বিমা নেই।"},
))

MOM_IDLE_SURPLUS = _reg(ReasonCodeSpec(
    code="MOM-006",
    title="Idle surplus held in savings beyond threshold period",
    description="Balance persistently above buffer plus threshold for three or more months.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "You have kept {amount} idle for {months} months.", "hi": "{months} महीनों से आपके खाते में {amount} बिना उपयोग के पड़े हैं।", "mr": "{months} महिन्यांपासून तुमच्या खात्यात {amount} वापराविना पडून आहेत.", "ta": "{months} மாதங்களாக உங்கள் கணக்கில் {amount} பயன்படுத்தப்படாமல் உள்ளது.", "bn": "{months} মাস ধরে আপনার অ্যাকাউন্টে {amount} অব্যবহৃত পড়ে আছে।"},
))

MOM_SEASONAL_WINDOW = _reg(ReasonCodeSpec(
    code="MOM-007",
    title="Seasonal input window approaching for agricultural profile",
    description="Sowing window approaching on an AGRICULTURAL income profile.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "Sowing season is close. Repayment can be timed to your harvest.", "hi": "आपके क्षेत्र में बुवाई का मौसम शुरू हो रहा है।", "mr": "तुमच्या भागात पेरणीचा हंगाम सुरू होत आहे.", "ta": "உங்கள் பகுதியில் விதைப்புப் பருவம் தொடங்குகிறது.", "bn": "আপনার এলাকায় বপনের মরসুম শুরু হচ্ছে।"},
))

# --- Sentinel (§6.3, §6.4) --------------------------------------------------

SEN_STRESS_PREDICTED = _reg(ReasonCodeSpec(
    code="SEN-001",
    title="Pre-delinquency stress predicted; PD uplift over 90 days",
    description=(
        "Reported as a probability-of-default uplift so existing risk systems can "
        "consume it directly rather than as a proprietary score (report §6.3)."
    ),
    polarity=Polarity.ADVERSE,
    templates={
        "en": "This month looks tight — your next instalment is due in {days} days.",
        "hi": "यह महीना तंग लग रहा है — आपकी अगली किस्त {days} दिनों में देय है।",
        "mr": "हा महिना ओढाताणीचा दिसतो — तुमचा पुढचा हप्ता {days} दिवसांत देय आहे.",
        "ta": "இந்த மாதம் இறுக்கமாகத் தெரிகிறது — உங்கள் அடுத்த தவணை {days} நாட்களில் செலுத்த வேண்டும்.",
        "bn": "এই মাসটি টানাটানির মনে হচ্ছে — আপনার পরের কিস্তি {days} দিনের মধ্যে দিতে হবে।",
    },
))

SEN_STRESS_DUE_NOW = _reg(ReasonCodeSpec(
    code="SEN-006",
    title="Pre-delinquency stress predicted; instalment already due",
    description=(
        "The same signal as SEN-001, said differently because the instalment is "
        "due today or the due date could not be projected. A day count is not "
        "rendered rather than rendered as zero: 'due in 0 days' is not something "
        "anyone says, and a sentence the customer has to decode is a sentence "
        "that failed."
    ),
    polarity=Polarity.ADVERSE,
    templates={
        "en": "This month looks tight, and your next instalment is due now.",
        "hi": "यह महीना तंग लग रहा है, और आपकी अगली किस्त अभी देय है।",
        "mr": "हा महिना ओढाताणीचा दिसतो, आणि तुमचा पुढचा हप्ता आत्ता देय आहे.",
        "ta": "இந்த மாதம் இறுக்கமாகத் தெரிகிறது, உங்கள் அடுத்த தவணை இப்போது செலுத்த வேண்டியது.",
        "bn": "এই মাসটি টানাটানির মনে হচ্ছে, আর আপনার পরের কিস্তি এখনই দিতে হবে।",
    },
))

SEN_CORRELATED_EMPLOYER = _reg(ReasonCodeSpec(
    code="SEN-002",
    title="Correlated portfolio stress: shared employer payroll delay",
    description=(
        "Salary-credit timing grouped by employer shows a cluster deviation. This is "
        "one payroll event, not N independent borrower events (report §6.3)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={"en": "Your salary has not arrived on its usual date.", "hi": "आपके जैसे कई ग्राहकों को इस महीने वेतन देर से मिला है।", "mr": "तुमच्यासारख्या अनेक ग्राहकांना या महिन्यात पगार उशिरा मिळाला आहे.", "ta": "உங்களைப் போன்ற பல வாடிக்கையாளர்களுக்கு இந்த மாதம் சம்பளம் தாமதமாகியுள்ளது.", "bn": "আপনার মতো অনেক গ্রাহকের এই মাসে বেতন দেরিতে এসেছে।"},
))

SEN_FRAUD_HOLD = _reg(ReasonCodeSpec(
    code="SEN-003",
    title="Fraud pattern matched; cooling-off hold applied",
    description="Device, beneficiary-novelty and velocity features matched a Table 4 pattern.",
    polarity=Polarity.ADVERSE,
    templates={
        "en": "This transfer is on hold for {minutes} minutes. You can cancel it. We will never ask you for an OTP or PIN.",
        "hi": "यह ट्रांसफ़र {minutes} मिनट के लिए रोका गया है। आप इसे रद्द कर सकते हैं। हम कभी OTP या PIN नहीं मांगेंगे।",
        "mr": "आम्ही हे {minutes} मिनिटे थांबवले आहे. तुम्हाला हवे असल्यास रद्द करू शकता.",
        "ta": "இதை {minutes} நிமிடங்கள் நிறுத்தி வைத்துள்ளோம். வேண்டுமெனில் ரத்து செய்யலாம்.",
        "bn": "আমরা এটি {minutes} মিনিট আটকে রেখেছি। চাইলে বাতিল করতে পারেন।",
    },
))

SEN_BENIGN_CHANGE = _reg(ReasonCodeSpec(
    code="SEN-004",
    title="Deviation attributed to benign life change",
    description="Pattern deviation explained by relocation, family event or seasonal norm.",
    polarity=Polarity.NEUTRAL,
    templates={"en": "Your spending changed, but it looks like a life change rather than a problem.", "hi": "आपका खर्च बदला है, पर यह चिंता की बात नहीं लगती।", "mr": "तुमचा खर्च बदलला आहे, पण ती काळजीची बाब वाटत नाही.", "ta": "உங்கள் செலவு மாறியுள்ளது, ஆனால் அது கவலைக்குரியதாகத் தெரியவில்லை.", "bn": "আপনার খরচ বদলেছে, তবে তা উদ্বেগের মনে হচ্ছে না।"},
))

SEN_UNWILLING = _reg(ReasonCodeSpec(
    code="SEN-005",
    title="Non-payment with healthy balance and sustained discretionary spend",
    description=(
        "Ability-versus-willingness separation indicates unwillingness. Forbearance "
        "is withheld and the account routes to standard recovery (report §6.3)."
    ),
    polarity=Polarity.ADVERSE,
    adverse_action=True,
    templates={"en": "We were not able to confirm a hardship on this account.", "hi": "यह मामला सामान्य वसूली प्रक्रिया से आगे बढ़ेगा।", "mr": "हे प्रकरण नेहमीच्या वसुली प्रक्रियेनुसार पुढे जाईल.", "ta": "இந்த வழக்கு வழக்கமான வசூல் நடைமுறையின்படி தொடரும்.", "bn": "এই ক্ষেত্রে স্বাভাবিক আদায় প্রক্রিয়া অনুসরণ করা হবে।"},
))

# --- Intervention ladder (§5.3) ---------------------------------------------

INT_EMI_DATE_SHIFT = _reg(ReasonCodeSpec(
    code="INT-001",
    title="EMI date shift proposed (servicing change, not a concession)",
    description=(
        "Aligning the due date to observed income arrival. Ordinarily treated as a "
        "servicing change rather than a concession granted for financial difficulty — "
        "real relief at effectively no regulatory cost (report §5.3). "
        "STATUS: design hypothesis, to be verified against current RBI circulars."
    ),
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "We can move your EMI from the {old} to the {new} — after your income arrives. Nothing else changes.",
        "hi": "हम आपकी EMI {old} से {new} कर सकते हैं — आपकी आमदनी आने के बाद। और कुछ नहीं बदलेगा।",
        "mr": "आम्ही तुमचा हप्ता {old} तारखेवरून {new} तारखेला हलवू शकतो, म्हणजे तो पगारानंतर येईल. काहीही जास्त खर्च नाही.",
        "ta": "உங்கள் தவணையை {old}-ஆம் தேதியிலிருந்து {new}-ஆம் தேதிக்கு மாற்றலாம், அப்போது அது வருமானத்துக்குப் பிறகு வரும். கூடுதல் செலவு இல்லை.",
        "bn": "আমরা আপনার কিস্তি {old} তারিখ থেকে {new} তারিখে সরাতে পারি, যাতে তা আয়ের পরে পড়ে। বাড়তি খরচ নেই।",
    },
))

INT_TENURE_EXTENSION = _reg(ReasonCodeSpec(
    code="INT-002",
    title="Tenure extension proposed (carries classification consequences)",
    description=(
        "Higher rung on the Intervention Ladder. Granted on account of borrower "
        "financial difficulty this generally carries asset-classification and "
        "provisioning consequences; the additional total cost is disclosed to the "
        "customer before consent (report §9.3)."
    ),
    polarity=Polarity.NEUTRAL,
    templates={
        "en": "A longer tenure lowers the monthly payment to {emi}, but you would pay {extra} more overall.",
        "hi": "लंबी अवधि से मासिक किस्त {emi} हो जाएगी, लेकिन कुल मिलाकर आप {extra} अधिक देंगे।",
        "mr": "आम्ही मुदत वाढवून हप्ता {emi} करू शकतो; एकूण {extra} जास्त पडेल.",
        "ta": "காலத்தை நீட்டி தவணையை {emi} ஆக்கலாம்; மொத்தத்தில் {extra} கூடுதல்.",
        "bn": "মেয়াদ বাড়িয়ে কিস্তি {emi} করা যায়; মোট {extra} বেশি পড়বে।",
    },
))

# --- Profitability / structuring (§10.1) ------------------------------------

PRF_TWIN_SAFE_EXPOSURE = _reg(ReasonCodeSpec(
    code="PRF-001",
    title="Amount set at Twin-safe exposure rather than maximum eligibility",
    description=(
        "Default system behaviour, not an exception: limits are sized to what the "
        "simulation sustains, not to the largest approvable figure (report §5.2)."
    ),
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "You are eligible for {eligible}. We recommend {recommended}, because that is what your cash flow carries comfortably.",
        "hi": "आप {eligible} के पात्र हैं। हम {recommended} की सलाह देते हैं, क्योंकि आपका कैश फ़्लो इतना आराम से संभाल लेगा।",
        "mr": "तुम्ही {eligible} साठी पात्र आहात, पण आम्ही {recommended} सुचवतो — तेवढेच तुमच्या रोख प्रवाहात बसते.",
        "ta": "நீங்கள் {eligible}-க்குத் தகுதியானவர், ஆனால் {recommended} பரிந்துரைக்கிறோம் — அதுவே உங்கள் பணப்புழக்கத்தில் பொருந்தும்.",
        "bn": "আপনি {eligible} পর্যন্ত যোগ্য, তবে আমরা {recommended} সুপারিশ করছি — ততটুকুই আপনার নগদ প্রবাহে মেলে।",
    },
))

PRF_DATE_ALIGNED = _reg(ReasonCodeSpec(
    code="PRF-002",
    title="Repayment date aligned to observed income arrival",
    description="EMI date selected to fall shortly after the detected income credit date.",
    polarity=Polarity.FAVOURABLE,
    templates={"en": "Your EMI is set for the {day}, two days after your income usually arrives.", "hi": "हमने आपकी किस्त की तारीख़ {day} रखी है, ताकि वह आपकी आमदनी आने के बाद पड़े।", "mr": "आम्ही तुमच्या हप्त्याची तारीख {day} ठेवली आहे, म्हणजे ती उत्पन्न आल्यानंतर येते.", "ta": "உங்கள் தவணைத் தேதியை {day}-ஆம் தேதி வைத்துள்ளோம், அது வருமானம் வந்த பிறகு வரும்.", "bn": "আমরা আপনার কিস্তির তারিখ {day} রেখেছি, যাতে তা আয় আসার পরে পড়ে।"},
))

# --- Counterfactual (§5.1) --------------------------------------------------

CFA_AVAILABLE = _reg(ReasonCodeSpec(
    code="CFA-001",
    title="Counterfactual structure computed",
    description=(
        "The Twin never merely refuses. This code carries the exact structure at "
        "which the declined product becomes affordable."
    ),
    polarity=Polarity.FAVOURABLE,
    templates={
        "en": "At {amount} over {tenure} months it would work — that is {emi} a month.",
        "hi": "{amount} की राशि {tenure} महीनों में संभव है — यानी हर महीने {emi}।",
        "mr": "{tenure} महिन्यांत {amount} चालेल — म्हणजे दरमहा {emi}.",
        "ta": "{tenure} மாதங்களில் {amount} சரியாக இருக்கும் — அதாவது மாதம் {emi}.",
        "bn": "{tenure} মাসে {amount} চলবে — অর্থাৎ মাসে {emi}।",
    },
))
