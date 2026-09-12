"""Fairness monitoring and the release-gate probes.

Report §9.5. Two things are measured, and the second is the one that matters:

* **Error parity** — are the model's mistakes distributed evenly across slices?
* **Benefit distribution** — *who receives the favourable offers*: cheap credit,
  savings, protection. A system can have perfectly equal error rates while
  quietly routing every good offer to one cohort, and only the second measure
  catches it.

Slices are gender, rural/urban, language, thin-file status and income type.
Note what is absent: the slice attributes are used to *measure*, never to
decide. Report §7.3 makes that separation explicit, and it is how a proxy for a
protected attribute is prevented from silently becoming an approval rule.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..core.types import CustomerProfile, GateOutcome


@dataclass(frozen=True)
class Slice:
    dimension: str
    value: str

    def key(self) -> str:
        return f"{self.dimension}={self.value}"


def slices_for(profile: CustomerProfile, *, gender: str | None = None) -> tuple[Slice, ...]:
    out = [
        Slice("location", "rural" if profile.is_rural else "urban"),
        Slice("language", profile.language),
        Slice("file", "thin" if profile.thin_file else "bureau"),
        Slice("income_type", profile.income_type.value),
    ]
    if gender:
        out.append(Slice("gender", gender))
    return tuple(out)


@dataclass
class SliceStats:
    decisions: int = 0
    favourable: int = 0
    suppressed: int = 0
    protected: int = 0

    @property
    def benefit_rate(self) -> float:
        return self.favourable / self.decisions if self.decisions else 0.0


@dataclass
class FairnessMonitor:
    """Rolling benefit-distribution statistics across slices."""

    tolerance: float = 0.20                 # relative gap against the population rate
    min_slice_size: int = 30                # below this, a gap is noise
    stats: dict[str, SliceStats] = field(default_factory=lambda: defaultdict(SliceStats))
    population: SliceStats = field(default_factory=SliceStats)

    def record(
        self, profile: CustomerProfile, outcome: GateOutcome, *, gender: str | None = None
    ) -> None:
        favourable = outcome is GateOutcome.ACT
        for s in slices_for(profile, gender=gender):
            st = self.stats[s.key()]
            st.decisions += 1
            st.favourable += int(favourable)
            st.suppressed += int(outcome is GateOutcome.SUPPRESS)
            st.protected += int(outcome is GateOutcome.PROTECT)
        self.population.decisions += 1
        self.population.favourable += int(favourable)

    def gap(self, slice_key: str) -> float:
        """Relative benefit gap of a slice against the population."""
        st = self.stats.get(slice_key)
        if not st or st.decisions < self.min_slice_size or self.population.benefit_rate == 0:
            return 0.0
        return (st.benefit_rate - self.population.benefit_rate) / self.population.benefit_rate

    def breaching_slices(self) -> list[tuple[str, float]]:
        return [
            (key, round(self.gap(key), 4))
            for key in self.stats
            if abs(self.gap(key)) > self.tolerance
        ]

    def check(self, profile: CustomerProfile, *, gender: str | None = None) -> tuple[bool, str]:
        """Gate check six: does this customer sit in a slice currently out of tolerance?

        A breach holds the decision for human review rather than flipping it.
        Auto-correcting an individual decision to fix an aggregate statistic
        would be both unexplainable and, applied to a protected attribute,
        exactly the thing being guarded against.
        """
        for s in slices_for(profile, gender=gender):
            g = self.gap(s.key())
            if abs(g) > self.tolerance:
                return False, (
                    f"Benefit rate for {s.key()} is {g:+.1%} against the population "
                    f"rate; outside the ±{self.tolerance:.0%} tolerance."
                )
        return True, "All fairness slices within tolerance."

    def report(self) -> dict:
        """The banker console's fairness view (report §6.7)."""
        return {
            "population_benefit_rate": round(self.population.benefit_rate, 4),
            "population_decisions": self.population.decisions,
            "slices": {
                key: {
                    "decisions": st.decisions,
                    "benefit_rate": round(st.benefit_rate, 4),
                    "gap_vs_population": round(self.gap(key), 4),
                    "suppressed": st.suppressed,
                    "protected": st.protected,
                    "in_tolerance": abs(self.gap(key)) <= self.tolerance,
                }
                for key, st in sorted(self.stats.items())
            },
            "breaching": self.breaching_slices(),
        }


# --- the published exclusion list -------------------------------------------
#
# Report §9.5: naming what the system refuses to use is a stronger commitment
# than listing what it does. This constant is rendered verbatim in the customer
# privacy screen and in the banker console, so it is code rather than prose.

EXCLUDED_DATA_SOURCES: tuple[str, ...] = (
    "Contact list / phonebook scraping",
    "Device location harvesting",
    "Social-graph analysis",
    "Psychometric scoring",
    "Photo library or gallery access",
    "SMS inbox scraping",
    "Caste, religion or community inference",
)

# Ethically bounded alternate data, used to build history where a bureau file is
# thin — which is what brings women and first-time borrowers into scope at all.
PERMITTED_ALTERNATE_DATA: tuple[str, ...] = (
    "Utility bill payment regularity",
    "Rent paid through UPI",
    "Mobile recharge regularity",
    "Self-help group repayment records",
    "Own-bank transaction history under consent",
)


DEFAULT_MONITOR = FairnessMonitor()
