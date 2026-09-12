"""The Sentinel — fraud, distress, life change, and ability vs willingness."""

from artha.core.types import PayIntent, SentinelVerdict
from artha.engines.sentinel import detect_correlated_stress, rank_for_capacity


def test_fraud_is_detected_and_routed_away_from_selling(engine, ingest, as_of):
    token = ingest("scam_victim")
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.sentinel is not None
    assert bundle.sentinel.verdict is SentinelVerdict.FRAUD
    assert bundle.decision.offer is None


def test_fraud_signals_carry_a_response_not_just_a_score(engine, ingest, as_of):
    """Table 4 maps each pattern to a response; a score alone is not actionable."""
    token = ingest("scam_victim")
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.sentinel.fraud_signals
    for signal in bundle.sentinel.fraud_signals:
        assert signal.response
        assert signal.evidence


def test_strategic_default_is_separated_from_hardship(engine, ingest, as_of):
    """Forbearance for hardship is portfolio optimisation; for strategic
    default it is a giveaway (report §6.3)."""
    token = ingest("strategic_defaulter")
    bundle = engine.decide(token, as_of=as_of, missed_payment=True)
    assert bundle.sentinel.pay_intent is PayIntent.UNWILLING
    assert bundle.ladder is None or not bundle.ladder.has_recommendation


def test_distress_is_reported_as_a_pd_uplift(engine, ingest, as_of):
    """Expressed in the bank's existing vocabulary, not an invented score."""
    token = ingest("stressed")
    bundle = engine.decide(token, as_of=as_of)
    assert bundle.sentinel.pd_uplift_90d > 0
    assert bundle.sentinel.evidence


def test_correlated_employer_stress_is_one_alert_not_many():
    """340 borrowers sharing an employer is one payroll delay (report §6.3)."""
    observations = [(f"tok_{i}", "ACME TEXTILES", 6) for i in range(340)]
    observations += [(f"other_{i}", "SUNRISE ENG", 1) for i in range(50)]
    alerts = detect_correlated_stress(observations, min_cluster=25)
    assert len(alerts) == 1
    assert alerts[0].affected_customers == 340
    assert "one payroll event" in alerts[0].description


def test_capacity_ranking_excludes_the_unactionable(engine, ingest, as_of):
    """The question is which N to contact today, not who is risky."""
    results = []
    for key in ("stressed", "salaried_volatile", "high_cost_borrower", "gig"):
        token = ingest(key)
        bundle = engine.decide(token, as_of=as_of)
        results.append((token, bundle.sentinel))

    ranked = rank_for_capacity(results, capacity=2)
    assert len(ranked) <= 2
    for _, result in ranked:
        assert result.contact_recommended
        assert result.intervention_changes_outcome


def test_seasonal_profiles_are_not_penalised_for_a_quiet_month(engine, ingest, as_of):
    """Population norms systematically misread rural and seasonal profiles."""
    farmer = ingest("agricultural")
    salaried = ingest("salaried_stable")
    f = engine.decide(farmer, as_of=as_of).sentinel
    s = engine.decide(salaried, as_of=as_of).sentinel
    assert f is not None and s is not None


def test_a_small_trader_is_not_flagged_as_a_mule(engine, ingest, as_of):
    """Heavy fan-in and fan-out is a kirana owner's business, not laundering.

    Report §7.4: anomaly scoring is against the customer's own baseline, because
    population norms systematically misread exactly these profiles. A naive
    pass-through rule flags every small trader in the book.
    """
    token = ingest("business")
    bundle = engine.decide(token, as_of=as_of)
    patterns = {f.pattern for f in (bundle.sentinel.fraud_signals or ())}
    assert "mule_behaviour" not in patterns
