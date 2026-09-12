"""Training entry points.

Report §7 and §8 name four learned components. They are specified here with
their training procedures and evaluation, and the shipped decision path does not
depend on any of them — it is rules plus simulation, which is why it is auditable
today. Running these turns each one on through the registry.

Every import that is not in the base runtime is lazy, so this module can be
imported in an environment without scikit-learn, XGBoost or SHAP.

    python -m artha.models.train narration
    python -m artha.models.train income-type
    python -m artha.models.train ranker

**All training data here is synthetic** (report §11.1). Retraining against real
portfolio data requires the reject-inference correction described in §7.2 —
repayment is observed only for approved customers, and the Suitability Gate
worsens that censoring by construction.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from ..core.types import Category, Direction
from ..ontology.enrich import DEFAULT_PIPELINE
from ..synth.generator import ARCHETYPES, SyntheticGenerator
from .registry import DEFAULT_REGISTRY, ModelRegistry, Stage


@dataclass(frozen=True)
class TrainingResult:
    model: str
    version: str
    rows: int
    metrics: dict[str, float]
    note: str = ""


def build_narration_corpus(*, months: int = 14, as_of: date | None = None):
    """Labelled narration strings from every archetype.

    The residual tail only — the rules and the merchant dictionary handle the
    bulk, and training the classifier on examples the rules already catch would
    measure the rules rather than the classifier.
    """
    as_of = as_of or date.today()
    generator = SyntheticGenerator()
    texts: list[str] = []
    labels: list[str] = []

    for key in ARCHETYPES:
        _, txns = generator.generate(key, months=months, end=as_of)
        result = DEFAULT_PIPELINE.run(txns, as_of=as_of)
        for enriched in result.enriched:
            if enriched.category is Category.UNCLASSIFIED:
                continue
            texts.append(enriched.txn.narration.lower())
            labels.append(enriched.category.value)
    return texts, labels


def train_narration_classifier(
    *, registry: ModelRegistry | None = None, version: str = "0.1.0"
) -> TrainingResult:
    """Character n-gram classifier for the residual tail (report §7.1).

    Character n-grams rather than words: Indian narration strings are full of
    concatenated tokens and inconsistent spacing, and a word tokeniser loses
    "SWIGGYSTORES" and "hpgas" entirely.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score, train_test_split
    from sklearn.pipeline import make_pipeline

    texts, labels = build_narration_corpus()
    if len(set(labels)) < 2:
        raise RuntimeError("corpus has fewer than two classes")

    pipeline = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True),
        LogisticRegression(max_iter=2000, class_weight="balanced"),
    )

    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=20260912, stratify=labels
    )
    pipeline.fit(x_train, y_train)
    accuracy = float(pipeline.score(x_test, y_test))
    cv = float(cross_val_score(pipeline, texts, labels, cv=3).mean())

    registry = registry or DEFAULT_REGISTRY
    registry.register(
        "narration", version, scorer=_ProbaScorer(pipeline), stage=Stage.SHADOW,
        metrics={"accuracy": round(accuracy, 4), "cv_accuracy": round(cv, 4)},
        training_rows=len(texts),
        notes="Char n-gram over the residual tail. Rules and the dictionary run first.",
    )
    return TrainingResult("narration", version, len(texts),
                          {"accuracy": accuracy, "cv_accuracy": cv})


def train_income_type_classifier(
    *, registry: ModelRegistry | None = None, version: str = "0.1.0"
) -> TrainingResult:
    """Supervised income typing over recurrence features (report §7.1).

    The rules classifier remains the baseline and stays registered, because it
    is the one that can be read aloud in a review meeting. This model is
    registered in SHADOW and must be promoted deliberately.
    """
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score

    import numpy as np

    from ..ontology.income_type import extract_features

    generator = SyntheticGenerator()
    rows: list[list[float]] = []
    labels: list[str] = []

    # Several seeds per archetype: one draw per class is not a training set.
    for seed_offset in range(8):
        gen = SyntheticGenerator(seed=20260912 + seed_offset)
        for key, arch in ARCHETYPES.items():
            _, txns = gen.generate(key, months=14)
            result = DEFAULT_PIPELINE.run(txns)
            features = extract_features(result.enriched, result.series)
            rows.append([v for _, v in sorted(features.as_dict().items())])
            labels.append(arch.expected_income_type.value)

    x = np.array(rows, dtype=float)
    y = np.array(labels)
    model = GradientBoostingClassifier(random_state=20260912)
    model.fit(x, y)
    cv = float(cross_val_score(model, x, y, cv=3).mean())

    registry = registry or DEFAULT_REGISTRY
    registry.register(
        "income_type", version, scorer=_ProbaScorer(model), stage=Stage.SHADOW,
        metrics={"cv_accuracy": round(cv, 4)}, training_rows=len(rows),
        notes="Rules classifier remains the baseline and the human override still wins.",
    )
    return TrainingResult("income_type", version, len(rows), {"cv_accuracy": cv})


def train_ranker(
    *, registry: ModelRegistry | None = None, version: str = "0.1.0"
) -> TrainingResult:
    """Suitability ranker with uplift targeting (report §7.2).

    The target is **estimated customer benefit, not propensity to convert.**
    Collaborative filtering is deliberately rejected: "customers like you also
    took" is precisely the mechanism that produces unsuitable offers, and it
    cannot be explained to a regulator.

    This is a transformed-outcome uplift formulation. Report §13.1 has moving to
    a causal-forest treatment-effect estimator once real intervention outcome
    data has accumulated; there is none yet, and saying so is more useful than
    shipping a causal claim built on synthetic labels.
    """
    raise NotImplementedError(
        "The ranker needs observed intervention outcomes to train against, and "
        "none exist at this stage — synthetic labels would produce a model that "
        "learns the generator rather than customer benefit. The deterministic "
        "candidate generation and rule-based ranking in artha.engines are the "
        "shipped path; see docs/CLAIMS_REGISTER.md."
    )


class _ProbaScorer:
    """Adapts a scikit-learn estimator to the registry's Scorer protocol."""

    def __init__(self, estimator) -> None:
        self.estimator = estimator

    def predict(self, x):
        return self.estimator.predict(x)

    def predict_proba(self, x):
        return self.estimator.predict_proba(x)

    @property
    def classes_(self):
        return self.estimator.classes_


_COMMANDS = {
    "narration": train_narration_classifier,
    "income-type": train_income_type_classifier,
    "ranker": train_ranker,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in _COMMANDS:
        print(f"usage: python -m artha.models.train [{' | '.join(_COMMANDS)}]")
        return 2
    result = _COMMANDS[argv[0]]()
    print(f"{result.model} v{result.version}: {result.rows} rows, {result.metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
