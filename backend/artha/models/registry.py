"""Model registry, champion/challenger and the kill switch.

Report §8, MLOps row: "Model registry, population-stability drift monitoring,
champion/challenger, kill switch — operational readiness and controlled
rollout." Report §9.6 adds that a documented kill switch must exist *for every
model*.

Three properties this enforces rather than documents:

* **Every scored decision names the model version that produced it.** The
  Decision Object carries `model_versions`, and an auditor asking why a customer
  was refused in March must be able to identify the artefact that refused them.
* **A challenger cannot affect a customer.** It scores in shadow and its output
  is recorded for comparison; promotion is an explicit, logged act.
* **The kill switch is the default path, not an escape hatch.** A killed model
  does not raise — it falls back to the registered rules baseline, because a
  decision service that stops answering during an incident is its own incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Protocol


class Stage(str, Enum):
    SHADOW = "SHADOW"          # scores, affects nothing
    CANARY = "CANARY"          # affects a bounded share of traffic
    CHAMPION = "CHAMPION"      # the production model
    RETIRED = "RETIRED"
    KILLED = "KILLED"          # switched off; traffic falls back to the baseline


class Scorer(Protocol):
    def predict(self, x: Any) -> Any: ...


@dataclass
class ModelVersion:
    name: str
    version: str
    stage: Stage
    scorer: Any = None
    baseline: Callable[[Any], Any] | None = None
    trained_at: str = ""
    training_rows: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    @property
    def key(self) -> str:
        return f"{self.name}:{self.version}"

    @property
    def live(self) -> bool:
        return self.stage in {Stage.CHAMPION, Stage.CANARY}


@dataclass(frozen=True)
class RegistryEvent:
    at: str
    model: str
    version: str
    action: str
    actor: str
    reason: str


class ModelRegistry:
    """Holds model versions and governs which one a decision may use."""

    def __init__(self) -> None:
        self._versions: dict[str, ModelVersion] = {}
        self._champion: dict[str, str] = {}       # model name -> version
        self._challenger: dict[str, str] = {}
        self._events: list[RegistryEvent] = []
        self._shadow_scores: list[dict] = []

    # -- registration -----------------------------------------------------

    def register(
        self,
        name: str,
        version: str,
        *,
        scorer: Any = None,
        baseline: Callable[[Any], Any] | None = None,
        stage: Stage = Stage.SHADOW,
        metrics: dict[str, float] | None = None,
        training_rows: int = 0,
        notes: str = "",
        actor: str = "system",
    ) -> ModelVersion:
        mv = ModelVersion(
            name=name, version=version, stage=stage, scorer=scorer, baseline=baseline,
            trained_at=datetime.now(UTC).isoformat(timespec="seconds"),
            training_rows=training_rows, metrics=dict(metrics or {}), notes=notes,
        )
        self._versions[mv.key] = mv
        if stage is Stage.CHAMPION:
            self._champion[name] = version
        self._log(name, version, f"register:{stage.value}", actor, notes)
        return mv

    def get(self, name: str, version: str) -> ModelVersion:
        return self._versions[f"{name}:{version}"]

    def champion(self, name: str) -> ModelVersion | None:
        version = self._champion.get(name)
        return self._versions.get(f"{name}:{version}") if version else None

    def challenger(self, name: str) -> ModelVersion | None:
        version = self._challenger.get(name)
        return self._versions.get(f"{name}:{version}") if version else None

    def versions(self, name: str | None = None) -> list[ModelVersion]:
        return [
            mv for mv in self._versions.values() if name is None or mv.name == name
        ]

    # -- promotion --------------------------------------------------------

    def set_challenger(self, name: str, version: str, *, actor: str, reason: str) -> None:
        mv = self.get(name, version)
        mv.stage = Stage.SHADOW
        self._challenger[name] = version
        self._log(name, version, "set_challenger", actor, reason)

    def promote(self, name: str, version: str, *, actor: str, reason: str) -> ModelVersion:
        """Make a version the champion. Always an explicit, logged act.

        Automatic promotion on a metric threshold is deliberately not offered.
        A model that can promote itself is one that can promote itself on a
        metric that drifted, and the first anyone would know is a supervisory
        question about a decision nobody chose to make.
        """
        mv = self.get(name, version)
        previous = self.champion(name)
        if previous and previous.version != version:
            previous.stage = Stage.RETIRED
            self._log(name, previous.version, "retire", actor, f"superseded by {version}")
        mv.stage = Stage.CHAMPION
        self._champion[name] = version
        if self._challenger.get(name) == version:
            self._challenger.pop(name)
        self._log(name, version, "promote", actor, reason)
        return mv

    def canary(self, name: str, version: str, *, actor: str, reason: str) -> ModelVersion:
        mv = self.get(name, version)
        mv.stage = Stage.CANARY
        self._log(name, version, "canary", actor, reason)
        return mv

    # -- the kill switch --------------------------------------------------

    def kill(self, name: str, *, actor: str, reason: str) -> list[str]:
        """Switch off every live version of a model.

        Returns the versions killed. Traffic then falls back to the registered
        rules baseline: report §9.6 requires a documented kill switch for every
        model, and a kill switch that takes the service down with it will not be
        pulled when it is needed.
        """
        killed: list[str] = []
        for mv in self._versions.values():
            if mv.name == name and mv.live:
                mv.stage = Stage.KILLED
                killed.append(mv.version)
                self._log(name, mv.version, "kill", actor, reason)
        self._champion.pop(name, None)
        return killed

    def revive(self, name: str, version: str, *, actor: str, reason: str) -> ModelVersion:
        mv = self.get(name, version)
        mv.stage = Stage.SHADOW
        self._log(name, version, "revive", actor, reason)
        return mv

    # -- scoring ----------------------------------------------------------

    def score(self, name: str, x: Any, *, customer_token: str = "") -> tuple[Any, str]:
        """Score with the champion, shadow-score the challenger, and say which ran.

        Returns ``(value, version_label)``. The label goes into the Decision
        Object's ``model_versions``, so the artefact that produced a number is
        always identifiable from the decision alone.
        """
        champion = self.champion(name)

        if champion is None or champion.scorer is None:
            baseline = self._baseline_for(name)
            if baseline is None:
                raise LookupError(f"no live model or baseline registered for '{name}'")
            return baseline(x), f"{name}:baseline-rules"

        value = champion.scorer.predict(x)

        challenger = self.challenger(name)
        if challenger is not None and challenger.scorer is not None:
            try:
                shadow = challenger.scorer.predict(x)
                self._shadow_scores.append({
                    "model": name,
                    "customer_token": customer_token,
                    "champion_version": champion.version,
                    "champion_value": value,
                    "challenger_version": challenger.version,
                    "challenger_value": shadow,
                })
            except Exception:
                # A challenger that errors must never affect the live path.
                pass

        return value, champion.key

    def _baseline_for(self, name: str) -> Callable[[Any], Any] | None:
        for mv in self._versions.values():
            if mv.name == name and mv.baseline is not None:
                return mv.baseline
        return None

    # -- observability ----------------------------------------------------

    @property
    def events(self) -> tuple[RegistryEvent, ...]:
        return tuple(self._events)

    @property
    def shadow_scores(self) -> tuple[dict, ...]:
        return tuple(self._shadow_scores)

    def summary(self) -> dict:
        return {
            "models": sorted({mv.name for mv in self._versions.values()}),
            "versions": [
                {
                    "name": mv.name, "version": mv.version, "stage": mv.stage.value,
                    "trained_at": mv.trained_at, "training_rows": mv.training_rows,
                    "metrics": dict(mv.metrics), "has_scorer": mv.scorer is not None,
                    "has_baseline": mv.baseline is not None,
                }
                for mv in sorted(self._versions.values(), key=lambda m: m.key)
            ],
            "champions": dict(self._champion),
            "challengers": dict(self._challenger),
            "shadow_comparisons": len(self._shadow_scores),
        }

    def _log(self, model: str, version: str, action: str, actor: str, reason: str) -> None:
        self._events.append(RegistryEvent(
            at=datetime.now(UTC).isoformat(timespec="seconds"),
            model=model, version=version, action=action, actor=actor, reason=reason,
        ))


DEFAULT_REGISTRY = ModelRegistry()
