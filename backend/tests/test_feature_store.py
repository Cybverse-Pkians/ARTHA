"""The consent-scoped feature store (report §4.2, §9.1).

The claim being tested is that privacy is enforced in the data layer rather than
asserted in a policy document: a revoked purpose makes the feature *absent*, not
merely unused.
"""

from datetime import date, timedelta

import pytest

from artha.consent.manager import ConsentManager
from artha.consent.purposes import Purpose
from artha.features.store import (
    FEATURE_REGISTRY,
    FeatureStore,
    UndeclaredFeature,
)

AS_OF = date(2026, 9, 12)


@pytest.fixture
def consent() -> ConsentManager:
    manager = ConsentManager()
    manager.grant_defaults("tok", as_of=AS_OF)
    return manager


@pytest.fixture
def store() -> FeatureStore:
    s = FeatureStore()
    s.put("tok", "monthly_income_paise", 4_200_000, as_of=AS_OF)
    s.put("tok", "balance_paise", 5_800_000, as_of=AS_OF)
    s.put("tok", "posture", "STEADY", as_of=AS_OF)
    s.put("tok", "contactable", True, as_of=AS_OF)
    return s


def test_every_feature_declares_a_purpose():
    for name, spec in FEATURE_REGISTRY.items():
        assert spec.purpose is not None, name
        assert spec.ttl_days > 0, name
        assert spec.source, name


def test_undeclared_features_are_refused(store):
    """A feature with no purpose attached is one revocation cannot reach."""
    with pytest.raises(UndeclaredFeature):
        store.put("tok", "shoe_size", 9, as_of=AS_OF)


def test_put_many_reports_what_it_skipped(store):
    skipped = store.put_many(
        "tok", {"balance_paise": 1, "astrological_sign": "leo"}, as_of=AS_OF
    )
    assert skipped == ["astrological_sign"]


def test_permitted_features_are_visible(store, consent):
    view = store.scoped_view("tok", consent, as_of=AS_OF)
    assert "monthly_income_paise" in view
    assert view.get("posture") == "STEADY"
    assert not view.exclusions


def test_revoking_a_purpose_removes_the_feature(store, consent):
    """The load-bearing test for report §9.1."""
    consent.revoke("tok", Purpose.MARKETING_CONTACT)
    view = store.scoped_view("tok", consent, as_of=AS_OF)

    assert "contactable" not in view
    assert view.get("contactable") is None
    assert "contactable" in view.excluded_names

    exclusion = next(e for e in view.exclusions if e.feature == "contactable")
    assert exclusion.reason == "purpose_revoked"
    assert "turned off" in exclusion.render()


def test_expired_features_are_excluded_on_read(store, consent):
    """TTL is enforced at read time, not by a cleanup job that may not have run.

    Consent is re-granted for a long window first, so this isolates the
    *feature* TTL from the *purpose* TTL — otherwise the consent grant lapses
    first and the exclusion is attributed to the wrong cause.
    """
    spec = FEATURE_REGISTRY["monthly_income_paise"]
    later = AS_OF + timedelta(days=spec.ttl_days + 1)
    consent.grant("tok", spec.purpose, as_of=AS_OF, ttl_days=3650)

    view = store.scoped_view("tok", consent, as_of=later)

    assert "monthly_income_paise" not in view
    exclusion = next(e for e in view.exclusions if e.feature == "monthly_income_paise")
    assert exclusion.reason == "expired"
    assert "retention limit" in exclusion.render()


def test_a_lapsed_permission_is_not_reported_as_a_revocation(store, consent):
    """Telling a customer they turned something off when it lapsed is untrue."""
    later = AS_OF + timedelta(days=400)
    view = store.scoped_view("tok", consent, as_of=later)
    reasons = {e.reason for e in view.exclusions}
    assert "purpose_expired" in reasons
    assert "purpose_revoked" not in reasons


def test_required_purposes_narrow_the_view_further(store, consent):
    """Purpose limitation applied a second time, at the point of use."""
    view = store.scoped_view(
        "tok", consent, as_of=AS_OF,
        required_purposes={Purpose.AFFORDABILITY_ASSESSMENT},
    )
    assert "monthly_income_paise" in view
    assert "contactable" not in view          # marketing purpose, not requested
    assert "balance_paise" not in view        # servicing purpose, not requested


def test_expiry_countdown_is_visible(store):
    """Report §9.1 asks for a visible countdown in the interface."""
    countdown = store.expiry_countdown("tok", as_of=AS_OF)
    assert countdown["monthly_income_paise"] == FEATURE_REGISTRY["monthly_income_paise"].ttl_days
    assert all(v >= 0 for v in countdown.values())


def test_erasure_removes_stored_values(store, consent):
    removed = store.forget("tok")
    assert removed >= 4
    assert not store.scoped_view("tok", consent, as_of=AS_OF).values


def test_engine_records_withheld_features_on_the_decision(engine, ingest, as_of):
    """The privacy ledger names what was withheld, not only what was used."""
    token = ingest("salaried_stable")
    engine.consent.revoke(token, Purpose.MARKETING_CONTACT)

    bundle = engine.decide(token, as_of=as_of)
    decision = bundle.decision

    assert "contactable" in decision.features_excluded
    assert "contactable" in decision.render_regulator()["consent"][
        "features_excluded_at_inference"
    ]
    assert "Withheld at inference" in decision.render_customer("en").privacy_note
