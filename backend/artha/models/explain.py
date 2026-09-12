"""Attribution for the Decision Object.

Report §7.6 requires SHAP contributions in the regulator rendering, and §7 gives
the reason gradient-boosted trees were chosen over a neural recommender in the
first place: "gradient-boosted trees with SHAP attribution are considerably more
auditable than a neural recommender."

Two things this module is careful about.

**It degrades to rule weights rather than to nothing.** The shipped decision path
is deterministic rules plus simulation, so there is frequently no model to
explain. An explainer that raises in that case would make the regulator
rendering conditional on a model being present, when the whole point is that the
rendering is always complete.

**It maps attributions onto reason codes.** A SHAP value against a feature name
is not an explanation a customer or a supervisor can use. Report §7.6 asks for
*ranked reason codes*, so attribution is translated into that vocabulary and the
raw values are retained alongside for the auditor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Which reason code a feature's contribution should be reported under. Anything
# unmapped is reported under its own name rather than dropped — a contribution
# nobody has assigned a reason to is exactly the one worth seeing.
FEATURE_TO_REASON: dict[str, str] = {
    "resilience_score": "AFF-002",
    "breach_probability": "AFF-001",
    "min_balance_p05_paise": "AFF-001",
    "obligation_to_income": "AFF-004",
    "existing_emi_paise": "AFF-004",
    "monthly_income_paise": "AFF-002",
    "income_volatility": "AFF-003",
    "income_type": "AFF-003",
    "credit_utilisation": "ELG-001",
    "bureau_score": "ELG-001",
    "thin_file": "ELG-002",
    "on_time_emi_streak": "ELG-001",
}


@dataclass(frozen=True)
class Attribution:
    feature: str
    contribution: float
    reason_code: str | None = None
    method: str = "rules"            # shap | rules

    @property
    def direction(self) -> str:
        return "increases" if self.contribution > 0 else "decreases"


@dataclass(frozen=True)
class Explanation:
    method: str
    attributions: tuple[Attribution, ...] = field(default_factory=tuple)
    base_value: float = 0.0
    note: str = ""

    def as_shap_dict(self) -> dict[str, float]:
        """The flat mapping the Decision Object carries."""
        return {a.feature: round(a.contribution, 6) for a in self.attributions}

    def ranked_reason_codes(self, limit: int = 5) -> list[tuple[str, float]]:
        totals: dict[str, float] = {}
        for a in self.attributions:
            if a.reason_code:
                totals[a.reason_code] = totals.get(a.reason_code, 0.0) + abs(a.contribution)
        return sorted(totals.items(), key=lambda kv: -kv[1])[:limit]


def explain(
    model: Any,
    features: dict[str, float],
    *,
    background: Any = None,
) -> Explanation:
    """Attribute a prediction, preferring SHAP and falling back to rule weights.

    ``shap`` and the tree model are imported lazily, so this module — and the
    package that imports it — works in an environment where neither is
    installed. That matters for the demo path and for anyone running the engine
    without the full ML stack.
    """
    if model is not None:
        shap_result = _try_shap(model, features, background)
        if shap_result is not None:
            return shap_result
    return _rule_attribution(features)


def _try_shap(model: Any, features: dict[str, float], background: Any) -> Explanation | None:
    try:
        import numpy as np
        import shap
    except ImportError:
        return None

    try:
        names = sorted(features)
        x = np.array([[float(features[n]) for n in names]])
        explainer = shap.TreeExplainer(model, data=background)
        values = explainer.shap_values(x)
        row = np.asarray(values)[0] if not isinstance(values, list) else np.asarray(values[0])[0]
        base = float(getattr(explainer, "expected_value", 0.0) or 0.0)
    except Exception:
        # SHAP failing must not fail the decision. The rule attribution below is
        # always available because it derives from the features themselves.
        return None

    attributions = tuple(
        Attribution(
            feature=name,
            contribution=float(row[i]),
            reason_code=FEATURE_TO_REASON.get(name),
            method="shap",
        )
        for i, name in enumerate(names)
    )
    return Explanation(
        method="shap",
        attributions=tuple(sorted(attributions, key=lambda a: -abs(a.contribution))),
        base_value=base,
        note="TreeExplainer attribution over the champion model.",
    )


def _rule_attribution(features: dict[str, float]) -> Explanation:
    """Deterministic attribution for the rules path.

    Not a model explanation and does not pretend to be one: `method` says
    "rules" and the note says so in words, so a regulator rendering can never be
    read as claiming a SHAP decomposition that was not computed.
    """
    weights = {
        "resilience_score": 0.9, "breach_probability": -1.0,
        "obligation_to_income": -0.8, "income_volatility": -0.5,
        "existing_emi_paise": -0.4, "monthly_income_paise": 0.6,
        "credit_utilisation": -0.5, "on_time_emi_streak": 0.4,
        "thin_file": -0.2,
    }
    attributions = tuple(
        Attribution(
            feature=name,
            contribution=round(weights[name] * _normalise(name, value), 4),
            reason_code=FEATURE_TO_REASON.get(name),
            method="rules",
        )
        for name, value in features.items()
        if name in weights
    )
    return Explanation(
        method="rules",
        attributions=tuple(sorted(attributions, key=lambda a: -abs(a.contribution))),
        note=(
            "Deterministic rule weights, not a SHAP decomposition. The shipped "
            "decision path is rules plus simulation; no trained model was scored."
        ),
    )


def _normalise(name: str, value: float) -> float:
    """Put features on a comparable scale so contributions can be ranked."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if name.endswith("_paise"):
        return min(v / 10_000_00, 1.0)
    if name == "resilience_score":
        return v / 100.0
    if name in {"breach_probability", "obligation_to_income", "credit_utilisation",
                "income_volatility", "thin_file"}:
        return min(max(v, 0.0), 1.0)
    if name == "on_time_emi_streak":
        return min(v / 24.0, 1.0)
    return v
