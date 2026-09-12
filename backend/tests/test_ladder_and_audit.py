"""The Intervention Ladder and the audit trail (report §5.3, §6.7, §9.4)."""

from artha.audit.log import RecordType
from artha.core.types import PayIntent, RecoveryState
from artha.intervention.ladder import Rung, lead_time_to_rung


def test_ladder_leads_with_the_zero_regulatory_cost_rung(engine, ingest, as_of):
    """Shifting the EMI date is real relief at effectively no regulatory cost.

    It is the highest-leverage intervention in the system, so it must be the one
    the ladder reaches for first.
    """
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.ladder is not None
    recommended = bundle.ladder.recommended
    assert recommended is not None
    assert recommended.rung is Rung.EMI_DATE_SHIFT
    assert recommended.economic_cost_paise == 0
    assert recommended.new_day_of_month is not None


def test_tenure_extension_is_never_presented_as_a_pure_benefit(engine, ingest, as_of):
    """Report §9.3: the additional total cost is stated before consent."""
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    alternatives = bundle.ladder.alternatives if bundle.ladder else ()
    extension = next((a for a in alternatives if a.rung is Rung.TENURE_EXTENSION), None)
    if extension is not None:
        assert extension.additional_total_cost_paise > 0
        assert "classification" in extension.regulatory_cost.lower()


def test_forbearance_is_withheld_from_strategic_default(engine, ingest, as_of):
    from artha.intervention.ladder import InterventionLadder

    token = ingest("strategic_defaulter")
    profile = engine.state(token).profile
    result = InterventionLadder().build(
        profile,
        current_emi_paise=profile.existing_emi_paise or 100_000,
        current_day_of_month=8,
        remaining_tenure_months=24,
        annual_rate=0.145,
        outstanding_paise=(profile.existing_emi_paise or 100_000) * 24,
        pay_intent=PayIntent.UNWILLING,
        as_of=as_of,
    )
    assert not result.has_recommendation
    assert result.withheld_reason


def test_lead_time_converts_into_rungs():
    """The model's job is to buy time; days convert into rungs (report §5.3)."""
    assert lead_time_to_rung(30) is Rung.EMI_DATE_SHIFT
    assert lead_time_to_rung(12) is Rung.PARTIAL_PREPAYMENT_PLAN
    assert lead_time_to_rung(5) is Rung.SHORT_PAYMENT_HOLIDAY
    assert lead_time_to_rung(None) is Rung.FORMAL_RESTRUCTURE
    assert lead_time_to_rung(30) < lead_time_to_rung(0)


def test_audit_chain_verifies(engine, ingest, as_of):
    token = ingest("stressed")
    engine.decide(token, as_of=as_of)
    ok, detail = engine.audit.verify()
    assert ok, detail


def test_tampering_breaks_the_chain(engine, ingest, as_of):
    token = ingest("stressed")
    engine.decide(token, as_of=as_of)
    original = engine.audit._records[0]
    engine.audit._records[0] = type(original)(
        **{**original.to_dict(), "record_type": original.record_type,
           "payload": {"tampered": True}}
    )
    ok, _ = engine.audit.verify()
    assert not ok


def test_detection_is_logged_separately_from_forbearance(engine, ingest, as_of):
    """The structural defence against an evergreening reading (report §9.4).

    Stress is reported to the risk function unconditionally; the decision to
    assist is a distinct, separately logged step. Nothing in the API allows the
    first to be suppressed because the second happened.
    """
    token = ingest("stressed")
    engine.decide(token, as_of=as_of)
    assert engine.audit.of_type(RecordType.STRESS_OBSERVATION)
    assert engine.audit.of_type(RecordType.INTERVENTION_OFFERED)

    pack = engine.audit.evidence_pack(token)
    assert pack["stress_observations"]
    assert pack["interventions"]
    assert pack["chain_integrity"]["verified"]


def test_injection_attempts_are_recorded(engine, ingest, as_of):
    """They changed nothing — but an attempt nobody counts is one nobody sees."""
    ingest("injection")
    records = engine.audit.of_type(RecordType.INJECTION_DETECTED)
    assert records
    assert records[0].payload["count"] >= 3


def test_recovery_state_transitions_carry_evidence(engine, ingest, as_of):
    token = ingest("stressed")
    engine.decide(token, as_of=as_of)
    record = engine.recovery.get(token)
    if record.state is not RecoveryState.STABLE:
        assert record.history
        assert record.history[-1].reason
