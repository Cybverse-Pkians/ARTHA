"""The vernacular journey: KFS, slot filling, degradation, consent (§6.2, §6.6)."""

import pytest

from artha.core.money import emi_paise, format_inr, rupees, total_cost_paise
from artha.journey.session import Channel, JourneyStore, Stage, video_kyc_preflight
from artha.language.adapters import detect_code_mixing, extract_amount, extract_tenure
from artha.language.kfs import build_kfs
from artha.llm.firewall import extract_numbers, is_grounded
from artha.products.catalogue import BY_ID, ProductOffer


@pytest.fixture
def offer() -> ProductOffer:
    product = BY_ID["pl_standard"]
    amount = rupees(100_000)
    emi = emi_paise(amount, product.annual_rate, 30)
    return ProductOffer(
        product=product, amount_paise=amount, eligible_amount_paise=rupees(250_000),
        tenure_months=30, emi_paise=emi, day_of_month=3,
        annual_rate=product.annual_rate,
        total_interest_paise=total_cost_paise(emi, 30, amount),
    )


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_kfs_states_the_total_extra_cost(offer, lang):
    kfs = build_kfs(offer, lang=lang)
    assert format_inr(offer.total_interest_paise) in kfs.spoken_script


def test_longer_tenures_are_priced(offer):
    """A longer tenure lowers the instalment and raises the total (report §9.3)."""
    kfs = build_kfs(offer)
    longer = [t for t in kfs.tenure_options if t.tenure_months > offer.tenure_months]
    assert longer
    for option in longer:
        assert option.additional_cost_vs_shortest_paise > 0
        assert option.emi_paise < offer.emi_paise


def test_every_numeral_in_the_spoken_kfs_is_grounded(offer):
    """The KFS must survive the firewall it will be read through."""
    kfs = build_kfs(offer, lang="en")
    ungrounded = [
        n for n in extract_numbers(kfs.spoken_script)
        if not is_grounded(n, kfs.numeric_ground)
    ]
    assert not ungrounded, ungrounded


@pytest.mark.parametrize(
    "utterance,expected_rupees",
    [
        ("mujhe ek lakh chahiye", 100_000),
        ("das lakh", 1_000_000),
        ("50000 rupaye", 50_000),
        ("मुझे 2 लाख चाहिए", 200_000),
        ("paanch lakh ka loan", 500_000),
    ],
)
def test_spoken_amounts_are_understood(utterance, expected_rupees):
    """People say "ek lakh", not "1 lakh". A digits-only parser re-asks forever."""
    result = extract_amount(utterance, 0.93, "hi")
    assert result.value == rupees(expected_rupees)


def test_large_amounts_are_always_read_back(offer):
    """₹1,00,000 misheard as ₹10,00,000 is an unacceptable failure mode.

    ASR confidence is a statement about acoustics, not about consequence.
    """
    result = extract_amount("paanch lakh", 0.99, "hi")
    assert result.needs_reask
    assert result.read_back


def test_low_confidence_forces_a_reask():
    result = extract_amount("ek lakh", 0.4, "hi")
    assert result.needs_reask
    assert result.reask_prompt


def test_tenure_in_years_converts_to_months():
    assert extract_tenure("do saal", 0.95, "hi").value == 24


def test_code_mixing_is_a_first_class_case():
    assert detect_code_mixing("mujhe ek lakh ka loan chahiye")
    assert detect_code_mixing("मुझे loan chahiye")


def test_degradation_ladder_reaches_a_feature_phone():
    """App → WhatsApp → IVR → SMS → USSD. The journey completes either way."""
    store = JourneyStore()
    session = store.create("tok", channel=Channel.APP)
    assert session.affordability_presentation() == "chart"
    session.degrade().degrade()
    assert session.channel is Channel.IVR
    assert session.affordability_presentation() == "spoken_sentence"
    session.degrade().degrade()
    assert session.channel is Channel.USSD
    assert session.affordability_presentation() == "sms_summary"


def test_abandoned_sessions_resume_where_they_stopped():
    store = JourneyStore()
    session = store.create("tok")
    session.advance(Stage.CONSENT).advance(Stage.AMOUNT_CAPTURE).abandon()
    session.resume(channel=Channel.WHATSAPP)
    assert session.stage is Stage.AMOUNT_CAPTURE
    assert session.channel is Channel.WHATSAPP


def test_prefilled_fields_carry_their_source():
    store = JourneyStore()
    session = store.create("tok")
    session.prefill("monthly_income", "₹42,000", "Own bank statement")
    session.prefill("pan", "XXXXX1234X", "DigiLocker")
    assert not session.unsourced_fields()


def test_video_kyc_preflight_blocks_before_a_slot_is_wasted():
    bad = video_kyc_preflight(
        lighting_lux=40, bandwidth_kbps=90, has_pan=False,
        has_aadhaar_ref=True, front_camera=True, battery_percent=8,
    )
    assert not bad.ready
    assert bad.blockers
    assert all(check.remedy for check in bad.blockers)


def test_assisted_mode_is_disclosed_to_the_customer():
    """The intermediary must not be able to misrepresent the terms (§6.2)."""
    store = JourneyStore()
    session = store.create("tok", assisted_by="bc_4471")
    assert session.session_banner()["assisted_notice"]


def test_safety_phrase_is_present_in_every_session():
    store = JourneyStore()
    session = store.create("tok")
    banner = session.session_banner()
    assert banner["safety_phrase"]
    assert "OTP" in banner["never_asks"]


# --- authored language coverage ---------------------------------------------


def test_every_reason_code_is_written_in_every_offered_language():
    """A missing template is a silent fallback to English on a customer screen.

    The app offers five languages, so a spec that carries fewer is a screen that
    quietly switches language mid-sentence for whoever picked the missing one.
    """
    from artha.core import reason_codes as rc

    offered = {"en", "hi", "mr", "ta", "bn"}
    missing = {
        code: sorted(offered - set(spec.templates))
        for code, spec in rc.all_codes().items()
        if offered - set(spec.templates)
    }
    assert not missing, f"reason codes missing translations: {missing}"


def test_translations_use_the_same_placeholders_as_the_english_template():
    """A renamed placeholder is worse than a missing translation.

    ``ReasonCodeSpec.say`` catches the KeyError and falls back to the *title* —
    so a mistyped placeholder shows the customer a supervisory heading like
    "Existing obligation ends within trigger window" instead of a sentence, and
    nothing raises to say so.
    """
    import re

    from artha.core import reason_codes as rc

    def holes(template: str) -> set[str]:
        return set(re.findall(r"\{(\w+)\}", template))

    mismatched = []
    for code, spec in rc.all_codes().items():
        expected = holes(spec.templates.get("en", ""))
        for lang, template in spec.templates.items():
            if holes(template) != expected:
                mismatched.append((code, lang, sorted(expected), sorted(holes(template))))
    assert not mismatched, f"placeholder mismatches: {mismatched}"


def test_the_key_fact_statement_is_written_in_every_offered_language():
    from artha.language import kfs

    offered = {"en", "hi", "mr", "ta", "bn"}
    for name, table in (
        ("labels", kfs._LABELS),
        ("script", kfs._SCRIPT),
        ("tenure warning", kfs._TENURE_WARNING),
        ("cooling off", kfs._COOLING_OFF),
        ("grievance", kfs._GRIEVANCE),
    ):
        assert offered <= set(table), f"{name} missing {sorted(offered - set(table))}"


def test_the_twin_speaks_every_offered_language():
    from artha.engines.twin import TWIN_SENTENCES, twin_sentence

    offered = {"en", "hi", "mr", "ta", "bn"}
    for key, table in TWIN_SENTENCES.items():
        assert offered <= set(table), f"twin sentence {key} missing a language"
    rendered = {twin_sentence("absorbs_one", {}, lang) for lang in offered}
    assert len(rendered) == len(offered), "a twin sentence fell back to another language"
