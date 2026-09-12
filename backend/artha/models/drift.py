"""Population-stability drift monitoring.

Report §8, MLOps row. The Population Stability Index is the standard the credit
risk function already reads, which is the reason to use it: a drift metric a
risk officer has to be taught is a drift metric nobody will act on.

Conventional interpretation, stated here because the thresholds are policy
rather than mathematics:

* PSI < 0.10 — no material shift
* 0.10 to 0.25 — moderate shift, investigate
* PSI >= 0.25 — significant shift, the model should not be trusted unreviewed

There is a second check that matters more for this system than raw PSI.
Report §9.5 requires fairness to be monitored by *slice*, so drift is computed
per slice as well as in aggregate: a model can be perfectly stable overall while
having drifted badly for rural or thin-file customers, and the aggregate number
hides exactly the cohort the report is concerned with.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MODERATE = 0.10
SIGNIFICANT = 0.25


@dataclass(frozen=True)
class DriftResult:
    feature: str
    psi: float
    severity: str                    # stable | moderate | significant
    bins: tuple[float, ...] = field(default_factory=tuple)
    expected_share: tuple[float, ...] = field(default_factory=tuple)
    actual_share: tuple[float, ...] = field(default_factory=tuple)

    @property
    def actionable(self) -> bool:
        return self.severity != "stable"


def population_stability_index(
    expected: np.ndarray | list[float],
    actual: np.ndarray | list[float],
    *,
    feature: str = "",
    bins: int = 10,
) -> DriftResult:
    """PSI of ``actual`` against the ``expected`` (training) distribution.

    Quantile bins are taken from the *expected* distribution, not from the
    combined sample. Binning on the combined sample would let a shifted actual
    distribution move the bin edges and partially hide its own shift.
    """
    expected_arr = np.asarray(expected, dtype=float)
    actual_arr = np.asarray(actual, dtype=float)

    if expected_arr.size < bins or actual_arr.size == 0:
        return DriftResult(feature, 0.0, "stable")

    edges = np.unique(np.quantile(expected_arr, np.linspace(0, 1, bins + 1)))
    if edges.size < 3:
        return DriftResult(feature, 0.0, "stable")
    edges[0], edges[-1] = -np.inf, np.inf

    expected_counts, _ = np.histogram(expected_arr, bins=edges)
    actual_counts, _ = np.histogram(actual_arr, bins=edges)

    # A zero bucket makes the log term infinite. The conventional correction is
    # a small floor; it is applied to both sides so the metric stays symmetric.
    eps = 1e-6
    expected_share = np.clip(expected_counts / expected_arr.size, eps, None)
    actual_share = np.clip(actual_counts / actual_arr.size, eps, None)

    psi = float(np.sum((actual_share - expected_share) * np.log(actual_share / expected_share)))

    if psi >= SIGNIFICANT:
        severity = "significant"
    elif psi >= MODERATE:
        severity = "moderate"
    else:
        severity = "stable"

    return DriftResult(
        feature=feature,
        psi=round(psi, 4),
        severity=severity,
        bins=tuple(float(e) for e in edges[1:-1]),
        expected_share=tuple(round(float(v), 4) for v in expected_share),
        actual_share=tuple(round(float(v), 4) for v in actual_share),
    )


def drift_report(
    expected: dict[str, list[float]],
    actual: dict[str, list[float]],
    *,
    bins: int = 10,
) -> dict:
    """PSI across every shared feature, worst first."""
    results = [
        population_stability_index(expected[name], actual[name], feature=name, bins=bins)
        for name in sorted(set(expected) & set(actual))
    ]
    results.sort(key=lambda r: -r.psi)
    return {
        "features": [
            {"feature": r.feature, "psi": r.psi, "severity": r.severity}
            for r in results
        ],
        "worst": results[0].feature if results else None,
        "worst_psi": results[0].psi if results else 0.0,
        "actionable": [r.feature for r in results if r.actionable],
        "thresholds": {"moderate": MODERATE, "significant": SIGNIFICANT},
    }


def sliced_drift(
    expected: dict[str, list[float]],
    actual_by_slice: dict[str, dict[str, list[float]]],
    *,
    bins: int = 10,
) -> dict:
    """Drift per fairness slice.

    A model can be stable in aggregate and badly drifted for rural or thin-file
    customers. Report §9.5 asks for fairness by slice; drift has the same
    problem and deserves the same treatment.
    """
    return {
        slice_key: drift_report(expected, actual, bins=bins)
        for slice_key, actual in sorted(actual_by_slice.items())
    }
