"""Model registry, drift monitoring and attribution (report §8, §7.6, §9.6)."""

import numpy as np
import pytest

from artha.models.drift import drift_report, population_stability_index, sliced_drift
from artha.models.explain import explain
from artha.models.registry import ModelRegistry, Stage


class _Constant:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, x):
        return self.value


class _Broken:
    def predict(self, x):
        raise RuntimeError("challenger exploded")


@pytest.fixture
def registry() -> ModelRegistry:
    r = ModelRegistry()
    r.register(
        "pd", "1.0.0", scorer=_Constant(0.05), baseline=lambda x: 0.055,
        stage=Stage.CHAMPION, metrics={"auc": 0.71},
    )
    return r


def test_scoring_names_the_version_that_produced_it(registry):
    """An auditor must be able to identify the artefact that refused someone."""
    value, version = registry.score("pd", {"x": 1})
    assert value == 0.05
    assert version == "pd:1.0.0"


def test_a_challenger_cannot_affect_a_customer(registry):
    registry.register("pd", "1.1.0", scorer=_Constant(0.99), stage=Stage.SHADOW)
    registry.set_challenger("pd", "1.1.0", actor="ds", reason="new features")

    value, version = registry.score("pd", {"x": 1}, customer_token="tok")

    assert value == 0.05                      # champion, not challenger
    assert version == "pd:1.0.0"
    assert registry.shadow_scores[-1]["challenger_value"] == 0.99


def test_a_broken_challenger_never_breaks_the_live_path(registry):
    registry.register("pd", "1.2.0", scorer=_Broken(), stage=Stage.SHADOW)
    registry.set_challenger("pd", "1.2.0", actor="ds", reason="experiment")
    value, _ = registry.score("pd", {"x": 1})
    assert value == 0.05


def test_promotion_is_explicit_and_logged(registry):
    registry.register("pd", "1.1.0", scorer=_Constant(0.02), stage=Stage.SHADOW)
    registry.promote("pd", "1.1.0", actor="risk-head", reason="approved at model committee")

    assert registry.champion("pd").version == "1.1.0"
    assert registry.get("pd", "1.0.0").stage is Stage.RETIRED

    promotion = [e for e in registry.events if e.action == "promote"][-1]
    assert promotion.actor == "risk-head"
    assert promotion.reason


def test_kill_switch_falls_back_to_the_baseline_rather_than_failing(registry):
    """Report §9.6: a kill switch that takes the service down will not be pulled."""
    killed = registry.kill("pd", actor="risk-head", reason="drift alert")

    assert killed == ["1.0.0"]
    assert registry.champion("pd") is None

    value, version = registry.score("pd", {"x": 1})
    assert value == 0.055
    assert version == "pd:baseline-rules"


def test_scoring_without_a_model_or_baseline_raises(registry):
    with pytest.raises(LookupError):
        registry.score("nonexistent", {"x": 1})


def test_psi_is_near_zero_for_an_unchanged_distribution():
    rng = np.random.default_rng(7)
    a = rng.normal(0, 1, 4000)
    b = rng.normal(0, 1, 4000)
    result = population_stability_index(a, b, feature="income")
    assert result.psi < 0.10
    assert result.severity == "stable"
    assert not result.actionable


def test_psi_detects_a_shifted_distribution():
    rng = np.random.default_rng(7)
    a = rng.normal(0, 1, 4000)
    b = rng.normal(1.6, 1, 4000)
    result = population_stability_index(a, b, feature="income")
    assert result.psi >= 0.25
    assert result.severity == "significant"
    assert result.actionable


def test_drift_report_orders_worst_first():
    rng = np.random.default_rng(11)
    expected = {"stable": list(rng.normal(0, 1, 2000)), "moved": list(rng.normal(0, 1, 2000))}
    actual = {"stable": list(rng.normal(0, 1, 2000)), "moved": list(rng.normal(2.0, 1, 2000))}
    report = drift_report(expected, actual)
    assert report["worst"] == "moved"
    assert "moved" in report["actionable"]


def test_drift_is_computed_per_fairness_slice():
    """A model can be stable overall and badly drifted for rural customers."""
    rng = np.random.default_rng(3)
    expected = {"income": list(rng.normal(0, 1, 2000))}
    by_slice = {
        "location=urban": {"income": list(rng.normal(0, 1, 2000))},
        "location=rural": {"income": list(rng.normal(2.2, 1, 2000))},
    }
    report = sliced_drift(expected, by_slice)
    assert report["location=urban"]["worst_psi"] < 0.10
    assert report["location=rural"]["worst_psi"] >= 0.25


def test_explanation_degrades_to_rule_weights_without_a_model():
    """The regulator rendering must never be conditional on a model existing."""
    result = explain(None, {
        "resilience_score": 88.0,
        "obligation_to_income": 0.42,
        "breach_probability": 0.02,
    })
    assert result.method == "rules"
    assert result.attributions
    assert "not a SHAP decomposition" in result.note
    assert result.as_shap_dict()


def test_attributions_map_onto_reason_codes():
    """A SHAP value against a feature name is not an explanation anyone can use."""
    result = explain(None, {"resilience_score": 90.0, "obligation_to_income": 0.5})
    ranked = result.ranked_reason_codes()
    assert ranked
    assert all(code.count("-") == 1 for code, _ in ranked)
