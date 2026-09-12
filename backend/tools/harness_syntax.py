"""Compile every module, then exercise the vernacular layer.

The API modules import fastapi and pydantic, which are not available under
Pyodide, so those are syntax-checked by compilation rather than imported. The
engine and vernacular modules are imported and run.
"""

from __future__ import annotations

import pathlib
import sys
import traceback

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def section(t):
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def main() -> int:
    section("1. Syntax — every module compiles")
    root = pathlib.Path("/app/artha")
    files = sorted(f for f in root.rglob("*.py") if not f.name.startswith("._"))
    bad = []
    for f in files:
        try:
            source = f.read_bytes().decode("utf-8")
        except UnicodeDecodeError as e:
            bad.append(f"{f.relative_to(root)}: not valid UTF-8 at byte {e.start}")
            continue
        try:
            compile(source, str(f), "exec")
        except SyntaxError as e:
            bad.append(f"{f.relative_to(root)}:{e.lineno}: {e.msg}")
    check(f"all {len(files)} modules compile", not bad, "; ".join(bad[:5]))

    section("2. Import graph — engine modules import cleanly")
    modules = [
        "artha.config", "artha.core.money", "artha.core.types",
        "artha.core.reason_codes", "artha.core.decision",
        "artha.ontology.narration", "artha.ontology.merchants",
        "artha.ontology.recurrence", "artha.ontology.income_type",
        "artha.ontology.enrich", "artha.features.builder",
        "artha.engines.twin", "artha.engines.moment",
        "artha.engines.profitability", "artha.engines.sentinel",
        "artha.gate.recovery", "artha.gate.conduct", "artha.gate.fairness",
        "artha.gate.suitability_gate", "artha.intervention.ladder",
        "artha.consent.purposes", "artha.consent.vault", "artha.consent.manager",
        "artha.llm.firewall", "artha.llm.capability",
        "artha.language.adapters", "artha.language.kfs",
        "artha.journey.session", "artha.products.catalogue",
        "artha.audit.log", "artha.synth.generator", "artha.orchestrator",
    ]
    failed = []
    for m in modules:
        try:
            __import__(m)
        except Exception as e:
            failed.append(f"{m}: {type(e).__name__}: {e}")
    check(f"all {len(modules)} engine modules import", not failed, "; ".join(failed[:3]))

    section("3. Key Fact Statement — the honest tenure trade-off (§6.2, §9.3)")
    from artha.core.money import format_inr, rupees
    from artha.engines.profitability import ProfitabilityEngine
    from artha.engines.twin import FinancialTwin
    from artha.language.kfs import build_kfs
    from artha.products.catalogue import BY_ID, ProductOffer
    from artha.core.money import emi_paise, total_cost_paise

    product = BY_ID["pl_standard"]
    amount = rupees(100_000)
    emi = emi_paise(amount, product.annual_rate, 30)
    offer = ProductOffer(
        product=product, amount_paise=amount, eligible_amount_paise=rupees(250_000),
        tenure_months=30, emi_paise=emi, day_of_month=3,
        annual_rate=product.annual_rate,
        total_interest_paise=total_cost_paise(emi, 30, amount),
    )

    for lang in ("en", "hi"):
        kfs = build_kfs(offer, lang=lang)
        print(f"\n  --- KFS ({lang})")
        print(f"      {kfs.spoken_script}")
        check(f"KFS renders in {lang}", len(kfs.spoken_script) > 80)
        check(f"KFS states total extra cost in {lang}",
              format_inr(offer.total_interest_paise) in kfs.spoken_script,
              format_inr(offer.total_interest_paise))
        longer = [t for t in kfs.tenure_options if t.tenure_months > offer.tenure_months]
        check(f"longer tenures are priced in {lang}",
              all(t.additional_cost_vs_shortest_paise > 0 for t in longer),
              f"{len(longer)} longer options")
        check(f"tenure warning present in {lang}",
              any(str(t.tenure_months) for t in longer) and
              format_inr(min(longer, key=lambda t: t.emi_paise).additional_cost_vs_shortest_paise)
              in kfs.spoken_script if longer else True)

    rec = [t for t in build_kfs(offer).tenure_options if t.is_recommended]
    check("recommended tenure is marked", len(rec) == 1, f"{len(rec)} marked")

    # The KFS must itself survive the firewall it will be read through.
    from artha.llm.firewall import AIFirewall, extract_numbers, is_grounded
    kfs = build_kfs(offer, lang="en")
    ungrounded = [n for n in extract_numbers(kfs.spoken_script)
                  if not is_grounded(n, kfs.numeric_ground)]
    check("every numeral in the spoken KFS is grounded", not ungrounded, str(ungrounded[:5]))

    section("4. Confidence-gated slot filling (§6.2)")
    from artha.language.adapters import detect_code_mixing, extract_amount, extract_tenure

    cases = [
        ("mujhe ek lakh chahiye", 0.95, 100_000, "one lakh, high confidence"),
        ("das lakh", 0.95, 1_000_000, "ten lakh"),
        ("50000 rupaye", 0.93, 50_000, "bare number"),
        ("मुझे 2 लाख चाहिए", 0.91, 200_000, "devanagari"),
    ]
    for text, conf, expected_rupees, label in cases:
        r = extract_amount(text, conf, "hi")
        ok = r.value == rupees(expected_rupees)
        check(f"amount parsed — {label}", ok,
              f"got {format_inr(r.value) if r.value else None} "
              f"conf={r.confidence} reask={r.needs_reask}")

    big = extract_amount("paanch lakh", 0.99, "hi")
    check("large amounts are always read back regardless of ASR confidence",
          big.needs_reask and bool(big.read_back), big.read_back)

    low = extract_amount("ek lakh", 0.4, "hi")
    check("low ASR confidence forces a re-ask", low.needs_reask and bool(low.reask_prompt),
          low.reask_prompt)

    t = extract_tenure("do saal", 0.95, "hi")
    check("tenure in years converts to months", t.value == 24, str(t.value))

    check("code-mixed input is recognised, not rejected",
          detect_code_mixing("mujhe ek lakh ka loan chahiye"))
    check("code-mixed script detected", detect_code_mixing("मुझे loan chahiye"))

    section("5. Journey — degradation, resume, pre-flight, anti-phishing (§6.2)")
    from artha.journey.session import Channel, JourneyStore, Stage, video_kyc_preflight

    store = JourneyStore()
    s = store.create("tok_demo", language="hi", channel=Channel.APP)
    check("safety phrase is issued on creation", bool(s.safety_phrase), s.safety_phrase)
    banner = s.session_banner()
    check("banner states what the assistant never asks",
          "OTP" in banner["never_asks"] and "PIN" in banner["never_asks"])

    check("app channel can render the Twin chart", s.affordability_presentation() == "chart")
    s.degrade(); s.degrade()
    check("degrades APP -> WHATSAPP -> IVR", s.channel is Channel.IVR, s.channel.value)
    check("IVR falls back to the spoken sentence",
          s.affordability_presentation() == "spoken_sentence")
    s.degrade(); s.degrade()
    check("ladder bottoms out at USSD", s.channel is Channel.USSD, s.channel.value)
    check("USSD still carries an affordability summary",
          s.affordability_presentation() == "sms_summary")

    s2 = store.create("tok_demo2")
    s2.advance(Stage.CONSENT).advance(Stage.AMOUNT_CAPTURE)
    s2.abandon()
    check("abandonment records the stage", s2.abandon_stage == Stage.AMOUNT_CAPTURE.value)
    s2.resume(channel=Channel.WHATSAPP)
    check("resume returns to the abandoned stage on another channel",
          s2.stage is Stage.AMOUNT_CAPTURE and s2.channel is Channel.WHATSAPP,
          f"{s2.stage.value} on {s2.channel.value}")

    s2.prefill("monthly_income", "₹42,000", "Own bank statement")
    s2.prefill("pan", "XXXXX1234X", "DigiLocker")
    check("prefilled fields carry their source", not s2.unsourced_fields(),
          str(s2.unsourced_fields()))

    ok_pre = video_kyc_preflight(lighting_lux=300, bandwidth_kbps=800, has_pan=True,
                                 has_aadhaar_ref=True, front_camera=True, battery_percent=80)
    check("pre-flight passes on a good device", ok_pre.ready)
    bad_pre = video_kyc_preflight(lighting_lux=40, bandwidth_kbps=90, has_pan=False,
                                  has_aadhaar_ref=True, front_camera=True, battery_percent=8)
    check("pre-flight blocks before a slot is wasted", not bad_pre.ready,
          ",".join(c.name for c in bad_pre.blockers))
    check("every blocker carries a remedy",
          all(c.remedy for c in bad_pre.blockers))

    assisted = store.create("tok_demo3", assisted_by="bc_4471")
    check("assisted mode is disclosed to the customer",
          assisted.session_banner()["assisted_notice"] is not None)

    section("6. Consent purposes and the privacy ledger (§6.6, §9.1)")
    from artha.consent.manager import ConsentManager, build_ledger_entry
    from artha.consent.purposes import Purpose
    from datetime import date

    as_of = date(2026, 9, 12)
    cm = ConsentManager()
    cm.grant_defaults("tok_x", as_of=as_of)
    check("defaults are granted at onboarding",
          cm.is_live("tok_x", Purpose.PRODUCT_RECOMMENDATION, as_of=as_of))
    check("fraud monitoring is not withdrawable",
          cm.revoke("tok_x", Purpose.FRAUD_MONITORING) is False)
    check("marketing consent is withdrawable",
          cm.revoke("tok_x", Purpose.MARKETING_CONTACT) is True)
    check("revoked purpose is no longer live",
          not cm.is_live("tok_x", Purpose.MARKETING_CONTACT, as_of=as_of))

    entry = build_ledger_entry(
        cm, decision_id="dec_1", customer_token="tok_x",
        purposes_used={Purpose.AFFORDABILITY_ASSESSMENT}, as_of=as_of, lang="en",
    )
    rendered = entry.render("en")
    check("ledger names what was used", len(rendered["used"]) >= 1, str(rendered["used"]))
    check("ledger names what was explicitly NOT used", len(rendered["not_used"]) >= 3,
          f"{len(rendered['not_used'])} purposes")
    check("ledger carries a one-tap revocation hint", bool(rendered["revoke"]))

    section("7. Tokenisation vault (§4.1)")
    from artha.consent.vault import TokenisationVault

    v = TokenisationVault(secret="test")
    t1 = v.tokenise("ABCDE1234F", kind="pan")
    t2 = v.tokenise("ABCDE1234F", kind="pan")
    check("tokenisation is deterministic", t1 == t2, t1)
    check("token does not contain the source value", "ABCDE1234F" not in t1)
    check("detokenisation requires a stated reason",
          v.detokenise(t1, reason="branch KYC review") == "ABCDE1234F")
    check("detokenisation is logged", len(v.access_log) == 1, str(v.access_log[0][1]))

    section("RESULT")
    print(f"  passed: {len(PASS)}   failed: {len(FAIL)}")
    if FAIL:
        print("\n  FAILURES:")
        for f in FAIL:
            print(f"   - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
