"""End-to-end pipeline verification for ARTHA.

Exercises the orchestrator across every archetype and asserts the behavioural
promises the report makes, not merely that the code runs.
"""

from __future__ import annotations

import sys
import traceback
from datetime import date, timedelta

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


def section(t):
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


def main() -> int:
    as_of = date(2026, 9, 12)

    from artha.audit.log import AuditLog, RecordType
    from artha.consent.manager import ConsentManager
    from artha.consent.purposes import Purpose
    from artha.core.money import format_inr, rupees
    from artha.core.types import GateOutcome, PayIntent, RecoveryState, SentinelVerdict
    from artha.engines.sentinel import detect_correlated_stress, rank_for_capacity
    from artha.engines.twin import FinancialTwin
    from artha.gate.conduct import EmpathyCalendar, LifeEvent, NudgeBudget
    from artha.gate.fairness import FairnessMonitor
    from artha.gate.recovery import RecoveryMachine
    from artha.orchestrator import ArthaEngine
    from artha.synth.generator import ARCHETYPES, SyntheticGenerator

    def fresh_engine():
        return ArthaEngine(
            twin=FinancialTwin(paths=400),
            recovery=RecoveryMachine(), budget=NudgeBudget(),
            calendar=EmpathyCalendar(), fairness=FairnessMonitor(),
            consent=ConsentManager(), audit=AuditLog(),
        )

    gen = SyntheticGenerator()

    def ingest(engine, key, **kw):
        arch = ARCHETYPES[key]
        token, txns = gen.generate(key, months=14, end=as_of)
        engine.consent.grant_defaults(token, as_of=as_of)
        defaults = dict(
            age=arch.age, dependants=arch.dependants, thin_file=arch.thin_file,
            district=arch.district, is_rural=arch.is_rural,
            tenure_with_bank_months=36, on_time_emi_streak=14,
            has_term_cover=arch.has_term_cover, has_health_cover=arch.has_health_cover,
            balance_paise=rupees(arch.opening_balance),
        )
        defaults.update(kw)
        engine.ingest(token, txns, as_of=as_of, **defaults)
        return token, arch

    # ------------------------------------------------------------------- 1
    section("1. End-to-end decisions across every archetype")
    outcomes = {}
    for key in ARCHETYPES:
        engine = fresh_engine()
        token, arch = ingest(engine, key)
        bundle = engine.decide(token, as_of=as_of)
        d = bundle.decision
        outcomes[key] = bundle

        cust = d.render_customer()
        reg = d.render_regulator()
        offer_txt = (
            f"{d.offer.product.name} {format_inr(d.offer.amount_paise)}"
            f"/{d.offer.tenure_months}m EMI {format_inr(d.offer.emi_paise)} "
            f"on the {d.offer.day_of_month}"
            if d.offer else "—"
        )
        print(f"\n  --- {key}: {arch.label}")
        print(f"      outcome={d.outcome.value}  offer={offer_txt}")
        print(f"      blocking_check={bundle.gate.blocking_check}")
        print(f"      says: {cust.headline!r}")
        if cust.counterfactual:
            print(f"      counterfactual: {cust.counterfactual!r}")
        print(f"      sentinel={bundle.sentinel.verdict.value} "
              f"pd_uplift={bundle.sentinel.pd_uplift_90d:+.1%} "
              f"intent={bundle.sentinel.pay_intent.value}")

        check(f"decision produced — {key}", d.decision_id.startswith("dec_"))
        check(f"gate trace non-empty — {key}", len(reg["gate_trace"]) >= 5,
              f"{len(reg['gate_trace'])} checks")
        check(f"regulator + customer renderings agree on outcome — {key}",
              reg["outcome"] == d.outcome.value)
        check(f"customer rendering is non-empty — {key}", bool(cust.headline.strip()),
              cust.headline[:60])
        check(f"every reason code resolves — {key}",
              all(r["title"] for r in reg["reason_codes"]),
              f"{len(reg['reason_codes'])} codes")

    # ------------------------------------------------------------------- 2
    section("2. The safeguards the report makes load-bearing")

    # 2a. A customer in stress is never sold to.
    engine = fresh_engine()
    token, _ = ingest(engine, "stressed")
    b = engine.decide(token, as_of=as_of)
    check("stressed customer is not sold a product",
          b.decision.outcome in {GateOutcome.PROTECT, GateOutcome.SUPPRESS}
          and b.decision.offer is None,
          f"outcome={b.decision.outcome.value}")
    check("stressed customer receives an intervention, not a flag",
          b.ladder is not None and b.ladder.has_recommendation,
          b.ladder.recommended.name if b.ladder and b.ladder.recommended else "none")
    if b.ladder and b.ladder.recommended:
        r = b.ladder.recommended
        print(f"      ladder rung {int(r.rung)}: {r.name} — {r.regulatory_cost[:60]}...")
        check("ladder leads with the zero-regulatory-cost rung", int(r.rung) == 1,
              f"rung {int(r.rung)} = {r.name}")
        check("EMI date shift costs nothing economically", r.economic_cost_paise == 0)

    # 2b. Recovery Mode suppresses selling in every family.
    engine.recovery.transition(token, RecoveryState.RECOVERY, reason="test", at=as_of)
    b2 = engine.decide(token, as_of=as_of)
    check("RECOVERY state suppresses all selling", b2.decision.offer is None,
          b2.decision.outcome.value)

    # 2c. Fraud beats everything.
    engine = fresh_engine()
    token, _ = ingest(engine, "scam_victim")
    b = engine.decide(token, as_of=as_of)
    check("fraud pattern routes to VERIFY, not a product",
          b.decision.outcome is GateOutcome.VERIFY and b.decision.offer is None,
          f"{b.decision.outcome.value}; signals="
          f"{[f.pattern for f in b.sentinel.fraud_signals]}")
    from artha.llm.firewall import AIFirewall as _FW
    _fraud_text = b.decision.render_customer().spoken
    check("fraud message passes the firewall in the customer's own language",
          _FW().validate(_fraud_text, b.decision).allowed,
          _FW().validate(_fraud_text, b.decision).blocked_detail or _fraud_text[:70])

    # 2d. Strategic default is not given forbearance.
    engine = fresh_engine()
    token, _ = ingest(engine, "strategic_defaulter")
    b = engine.decide(token, as_of=as_of, missed_payment=True)
    check("strategic defaulter identified as unwilling",
          b.sentinel.pay_intent is PayIntent.UNWILLING, b.sentinel.pay_intent.value)
    check("forbearance withheld from strategic defaulter",
          b.ladder is None or not b.ladder.has_recommendation,
          (b.ladder.withheld_reason[:70] if b.ladder else "no ladder built"))

    # 2e. Thin buffer + unstable income -> no credit at all.
    engine = fresh_engine()
    token, _ = ingest(engine, "gig")
    b = engine.decide(token, as_of=as_of)
    check("thin-buffer gig worker is offered no credit",
          b.decision.offer is None or b.decision.offer.product.family.value == "SAVINGS",
          b.decision.offer.product.name if b.decision.offer else "no offer")

    # ------------------------------------------------------------------- 3
    section("3. Conduct controls")
    engine = fresh_engine()
    token, _ = ingest(engine, "salaried_stable")

    first = engine.decide(token, as_of=as_of)
    print(f"      first decision: {first.decision.outcome.value} "
          f"{first.decision.offer.product.name if first.decision.offer else '—'}")

    if first.decision.outcome is GateOutcome.ACT:
        second = engine.decide(token, as_of=as_of)
        check("per-product cooldown blocks an immediate repeat",
              second.decision.outcome is not GateOutcome.ACT
              or second.decision.offer.product.family != first.decision.offer.product.family,
              f"second={second.decision.outcome.value} blocking={second.gate.blocking_check}")

    # nudge budget
    engine2 = fresh_engine()
    t2, _ = ingest(engine2, "salaried_stable")
    for i in range(engine2.budget.per_month):
        engine2.budget.record_contact(t2, f"FILLER_{i}", as_of)
    b = engine2.decide(t2, as_of=as_of)
    check("exhausted nudge budget suppresses", b.decision.outcome is not GateOutcome.ACT,
          f"{b.decision.outcome.value} blocking={b.gate.blocking_check}")

    # empathy calendar
    engine3 = fresh_engine()
    t3, _ = ingest(engine3, "salaried_stable")
    engine3.calendar.add(t3, LifeEvent.BEREAVEMENT, start=as_of - timedelta(days=5),
                         evidence="test window")
    b = engine3.decide(t3, as_of=as_of)
    check("empathy calendar suppresses during bereavement",
          b.decision.outcome is not GateOutcome.ACT,
          f"{b.decision.outcome.value} blocking={b.gate.blocking_check}")

    # consent revocation
    engine4 = fresh_engine()
    t4, _ = ingest(engine4, "salaried_stable")
    engine4.consent.revoke(t4, Purpose.PRODUCT_RECOMMENDATION)
    b = engine4.decide(t4, as_of=as_of)
    check("revoking a purpose stops the recommendation at inference time",
          b.decision.outcome is not GateOutcome.ACT,
          f"{b.decision.outcome.value} blocking={b.gate.blocking_check}")

    # ------------------------------------------------------------------- 4
    section("4. Twin-safe exposure and the counterfactual")
    engine = fresh_engine()
    token, arch = ingest(engine, "salaried_stable")
    b = engine.decide(token, as_of=as_of, requested_product_id="pl_standard",
                      requested_amount_paise=rupees(500000))
    d = b.decision
    if d.offer:
        print(f"      eligible {format_inr(d.offer.eligible_amount_paise)} -> "
              f"recommended {format_inr(d.offer.amount_paise)} "
              f"over {d.offer.tenure_months}m at {d.offer.annual_rate:.2%}")
        check("offer is sized at or below eligibility",
              d.offer.amount_paise <= d.offer.eligible_amount_paise)
        check("requested 5L is not granted blindly",
              d.offer.amount_paise <= rupees(500000))
    else:
        print(f"      no offer: {d.render_customer().headline}")
        check("refusal carries a counterfactual or an explicit blocker",
              d.counterfactual is not None or bool(d.render_customer().headline))

    # ------------------------------------------------------------------- 5
    section("5. AI Firewall — numeric grounding and forbidden content")
    from artha.llm.firewall import AIFirewall, FirewallOutcome, build_model_context

    fw = AIFirewall()
    engine = fresh_engine()
    token, _ = ingest(engine, "salaried_stable")
    b = engine.decide(token, as_of=as_of)
    d = b.decision

    honest = d.render_customer().spoken
    v = fw.validate(honest, d)
    check("the system's own rendering passes the firewall",
          v.outcome is FirewallOutcome.ALLOWED,
          f"{v.outcome.value} {v.blocked_detail} ungrounded={v.ungrounded[:5]}")

    hallucinated = "You are approved for ₹7,43,219 at 8.25% — a great rate."
    v = fw.validate(hallucinated, d)
    check("hallucinated amount is blocked",
          v.outcome is FirewallOutcome.BLOCKED_UNGROUNDED_NUMBER,
          f"{v.outcome.value} ungrounded={v.ungrounded[:4]}")
    check("blocked output falls back to the template", v.used_fallback and v.text == honest)

    for bad, label in [
        ("Please share the OTP sent to your phone to continue.", "credential request"),
        ("Hurry — this offer expires in 2 hours!", "manufactured urgency"),
        ("You are guaranteed approval for this loan.", "promised approval"),
    ]:
        v = fw.validate(bad, d)
        check(f"blocked: {label}", not v.allowed, v.blocked_detail)

    ctx = build_model_context(d)
    blob = str(ctx)
    check("model context contains no customer token", token not in blob)
    check("model context carries allowed_numbers", len(ctx["allowed_numbers"]) > 0,
          f"{len(ctx['allowed_numbers'])} values")

    # Devanagari numerals must not slip past grounding.
    v = fw.validate("आपको ९९९९९९ रुपये मिलेंगे।", d)
    check("Devanagari numerals are checked too", not v.allowed, v.outcome.value)

    # ------------------------------------------------------------------- 6
    section("6. Capability tokens — propose, preview, confirm, execute")
    from artha.llm.capability import Capability, CapabilityBroker, TokenRejected

    broker = CapabilityBroker(secret="test-secret", ttl_seconds=300)
    tok = broker.mint(Capability.ACCEPT_OFFER, decision_id=d.decision_id,
                      customer_token=token)

    try:
        broker.redeem(tok, customer_confirmed=False)
        check("unconfirmed redemption is rejected", False, "it was accepted")
    except TokenRejected as e:
        check("unconfirmed redemption is rejected", True, str(e))

    broker.redeem(tok, customer_confirmed=True, expected_capability=Capability.ACCEPT_OFFER)
    check("confirmed redemption succeeds", True)

    try:
        broker.redeem(tok, customer_confirmed=True)
        check("token is single-use", False, "replay accepted")
    except TokenRejected as e:
        check("token is single-use", True, str(e))

    forged = broker.mint(Capability.PRESENT_OFFER, decision_id="x", customer_token=token)
    try:
        broker.redeem(forged, customer_confirmed=True,
                      expected_capability=Capability.ACCEPT_OFFER)
        check("capability scope is enforced", False, "wrong capability accepted")
    except TokenRejected as e:
        check("capability scope is enforced", True, str(e))

    # ------------------------------------------------------------------- 7
    section("7. Portfolio-level correlated detection (§6.3)")
    observations = [(f"tok_{i}", "ACME TEXTILES", 6) for i in range(340)]
    observations += [(f"other_{i}", "SUNRISE ENG", 1) for i in range(50)]
    alerts = detect_correlated_stress(observations, min_cluster=25)
    check("employer payroll delay surfaces as ONE alert", len(alerts) == 1, f"{len(alerts)} alerts")
    if alerts:
        a = alerts[0]
        print(f"      {a.description}")
        check("alert counts all affected customers", a.affected_customers == 340,
              str(a.affected_customers))

    # capacity ranking
    results = []
    for key in ("stressed", "salaried_volatile", "high_cost_borrower", "gig"):
        e = fresh_engine()
        t, _ = ingest(e, key)
        bb = e.decide(t, as_of=as_of)
        results.append((t, bb.sentinel))
    ranked = rank_for_capacity(results, capacity=2)
    check("capacity ranking returns at most N", len(ranked) <= 2, f"{len(ranked)} of {len(results)}")
    check("capacity ranking excludes the unactionable",
          all(r.contact_recommended and r.intervention_changes_outcome for _, r in ranked))

    # ------------------------------------------------------------------- 8
    section("8. Audit trail — chain integrity and detection/forbearance split")
    engine = fresh_engine()
    token, _ = ingest(engine, "stressed")
    engine.decide(token, as_of=as_of)
    ok, detail = engine.audit.verify()
    check("audit chain verifies", ok, detail)

    stress_records = engine.audit.of_type(RecordType.STRESS_OBSERVATION)
    intervention_records = engine.audit.of_type(RecordType.INTERVENTION_OFFERED)
    check("stress is logged unconditionally", len(stress_records) >= 1,
          f"{len(stress_records)} stress observations")
    check("intervention is a separate record", len(intervention_records) >= 1,
          f"{len(intervention_records)} intervention records")

    pack = engine.audit.evidence_pack(token)
    check("evidence pack separates observation from forbearance",
          "stress_observations" in pack and "interventions" in pack
          and pack["chain_integrity"]["verified"])

    # tamper detection
    engine.audit._records[0] = engine.audit._records[0].__class__(
        **{**engine.audit._records[0].to_dict(),
           "record_type": engine.audit._records[0].record_type,
           "payload": {"tampered": True}}
    )
    ok2, detail2 = engine.audit.verify()
    check("tampering is detected", not ok2, detail2)

    # injection archetype logs a security event
    engine = fresh_engine()
    token, _ = ingest(engine, "injection")
    inj = engine.audit.of_type(RecordType.INJECTION_DETECTED)
    check("injection attempts are recorded", len(inj) >= 1,
          f"{inj[0].payload['count']} findings, patterns={inj[0].payload['patterns']}"
          if inj else "none")

    # ------------------------------------------------------------------- 9
    section("9. Suppression is reported as a success metric (§2.2)")
    engine = fresh_engine()
    suppressed = acted = protected = 0
    for key in ARCHETYPES:
        e = fresh_engine()
        t, _ = ingest(e, key)
        o = e.decide(t, as_of=as_of).decision.outcome
        suppressed += o is GateOutcome.SUPPRESS
        acted += o is GateOutcome.ACT
        protected += o is GateOutcome.PROTECT
    print(f"      across {len(ARCHETYPES)} archetypes: ACT={acted} "
          f"SUPPRESS={suppressed} PROTECT={protected}")
    check("the Gate actually refuses sometimes", suppressed + protected > 0)
    check("the Gate is not refusing everything", acted > 0,
          "if 0, the demo has nothing to show")

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
