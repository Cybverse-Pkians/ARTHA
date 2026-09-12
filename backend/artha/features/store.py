"""The consent-scoped feature store.

Report §4.2: "Enriched signals are stored in a consent-scoped feature store in
which every feature carries the consent purpose that permits it, a time-to-live
and its source. When a customer revokes a purpose, the associated features are
excluded at inference time — privacy is enforced in the data layer rather than
asserted in a policy document."

That last sentence is the whole design, and it only means something if the
feature is genuinely *absent* rather than merely unused. So:

* every feature must be declared in :data:`FEATURE_REGISTRY` before it can be
  written — an undeclared feature has no purpose attached and is refused;
* :meth:`FeatureStore.scoped_view` returns the permitted values **and an explicit
  record of every exclusion with its reason**, which is what lets the privacy
  ledger (§6.6) name what was not used rather than only what was;
* a time-to-live is enforced on read, not on a cleanup job, because a cleanup
  job that has not run yet is a policy document again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..consent.manager import ConsentManager, purpose_state
from ..consent.purposes import Purpose


@dataclass(frozen=True)
class FeatureSpec:
    """A declared feature: what permits it, how long it lives, where it came from."""

    name: str
    purpose: Purpose
    ttl_days: int
    source: str
    description: str


@dataclass(frozen=True)
class FeatureValue:
    spec: FeatureSpec
    value: Any
    computed_at: date

    def expires_on(self) -> date:
        return self.computed_at + timedelta(days=self.spec.ttl_days)

    def expired(self, as_of: date) -> bool:
        return as_of > self.expires_on()

    def days_remaining(self, as_of: date) -> int:
        return max((self.expires_on() - as_of).days, 0)


@dataclass(frozen=True)
class Exclusion:
    feature: str
    purpose: str
    reason: str          # purpose_revoked | purpose_expired | expired | undeclared

    def render(self) -> str:
        readable = self.purpose.lower().replace("_", " ")
        if self.reason == "purpose_revoked":
            return f"{self.feature} — you turned off {readable}"
        if self.reason == "purpose_expired":
            return f"{self.feature} — your permission for {readable} has lapsed and can be renewed"
        if self.reason == "expired":
            return f"{self.feature} — this data has passed its retention limit and was discarded"
        return f"{self.feature} — not permitted"


@dataclass(frozen=True)
class ScopedView:
    """What an engine is allowed to see, and what it is not."""

    values: dict[str, Any] = field(default_factory=dict)
    exclusions: tuple[Exclusion, ...] = field(default_factory=tuple)
    purposes_used: tuple[Purpose, ...] = field(default_factory=tuple)

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def __contains__(self, name: str) -> bool:
        return name in self.values

    @property
    def excluded_names(self) -> tuple[str, ...]:
        return tuple(e.feature for e in self.exclusions)


class UndeclaredFeature(KeyError):
    """Raised when writing a feature that carries no consent purpose.

    Failing loudly is the point. A feature that slips into the store without a
    declared purpose is a feature that revocation cannot reach, and it would do
    so silently.
    """


# --- the registry -----------------------------------------------------------
#
# Every feature the engines consume, with the purpose that permits it. The TTLs
# are deliberately short for anything derived from an Account Aggregator pull:
# report §9.1 requires AA data to be fetched against a stated purpose with a
# time-to-live and automatic expiry, with a visible countdown in the interface.

FEATURE_REGISTRY: dict[str, FeatureSpec] = {
    spec.name: spec
    for spec in (
        FeatureSpec("balance_paise", Purpose.ACCOUNT_SERVICING, 3650,
                    "Core banking CDC", "Current account balance."),
        FeatureSpec("monthly_income_paise", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Own-bank transaction history", "Assessed monthly income."),
        FeatureSpec("income_type", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Derived — recurrence features", "Detected income profile."),
        FeatureSpec("income_volatility", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Derived — recurrence features", "Coefficient of variation of income."),
        FeatureSpec("income_day_of_month", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Own-bank transaction history", "Observed income arrival day."),
        FeatureSpec("monthly_committed_outflow_paise", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Derived — detected recurring series", "Rent, utilities, premiums, fees."),
        FeatureSpec("monthly_discretionary_paise", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Derived — categorised spend", "Observed discretionary spend."),
        FeatureSpec("existing_emi_paise", Purpose.AFFORDABILITY_ASSESSMENT, 180,
                    "Derived — detected EMI series", "Existing instalment obligations."),
        FeatureSpec("posture", Purpose.PRODUCT_RECOMMENDATION, 180,
                    "Derived — cash-flow shape", "Financial posture segment."),
        FeatureSpec("dependants", Purpose.PRODUCT_RECOMMENDATION, 365,
                    "Customer declaration", "Number of dependants."),
        FeatureSpec("has_term_cover", Purpose.PRODUCT_RECOMMENDATION, 365,
                    "Own-bank product holdings", "Term cover held."),
        FeatureSpec("has_health_cover", Purpose.PRODUCT_RECOMMENDATION, 365,
                    "Own-bank product holdings", "Health cover held."),
        FeatureSpec("credit_utilisation", Purpose.CREDIT_BUREAU_PULL, 30,
                    "Credit bureau", "Revolving credit utilisation."),
        FeatureSpec("bureau_score", Purpose.CREDIT_BUREAU_PULL, 30,
                    "Credit bureau", "Bureau score."),
        FeatureSpec("external_obligations_paise", Purpose.AA_STATEMENT_PULL, 30,
                    "Account Aggregator", "Obligations visible at other institutions."),
        FeatureSpec("anomaly_baseline", Purpose.FRAUD_MONITORING, 3650,
                    "Derived — own-history baseline", "Per-customer spend baseline."),
        FeatureSpec("device_fingerprint", Purpose.FRAUD_MONITORING, 3650,
                    "Channel telemetry", "Known-device set."),
        FeatureSpec("pd_uplift_90d", Purpose.STRESS_EARLY_WARNING, 365,
                    "Derived — Sentinel", "Probability-of-default uplift."),
        FeatureSpec("contactable", Purpose.MARKETING_CONTACT, 365,
                    "Consent record", "May be contacted about offers."),
    )
}


class FeatureStore:
    """Per-customer feature values, retrieved only through a consent scope.

    In deployment this is a managed feature store; the contract is what matters
    and is what the tests hold. Engines never read it directly — they receive a
    :class:`~artha.core.types.CustomerProfile` built from a scoped view, so a
    revoked purpose removes a capability rather than merely filtering an output.
    """

    def __init__(self) -> None:
        self._values: dict[str, dict[str, FeatureValue]] = {}

    # -- writing ----------------------------------------------------------

    def put(
        self, customer_token: str, name: str, value: Any, *, as_of: date | None = None
    ) -> FeatureValue:
        spec = FEATURE_REGISTRY.get(name)
        if spec is None:
            raise UndeclaredFeature(
                f"'{name}' is not in FEATURE_REGISTRY. Declare it with the consent "
                f"purpose that permits it — an undeclared feature is one that "
                f"revocation cannot reach."
            )
        entry = FeatureValue(spec=spec, value=value, computed_at=as_of or date.today())
        self._values.setdefault(customer_token, {})[name] = entry
        return entry

    def put_many(
        self, customer_token: str, values: dict[str, Any], *, as_of: date | None = None
    ) -> list[str]:
        """Write what is declared, and report what was skipped.

        Returns the names that were refused, rather than raising, so a caller
        writing a whole profile is told about every undeclared field at once
        instead of one per round trip.
        """
        skipped: list[str] = []
        for name, value in values.items():
            if name not in FEATURE_REGISTRY:
                skipped.append(name)
                continue
            self.put(customer_token, name, value, as_of=as_of)
        return skipped

    # -- reading ----------------------------------------------------------

    def scoped_view(
        self,
        customer_token: str,
        consent: ConsentManager,
        *,
        as_of: date | None = None,
        required_purposes: set[Purpose] | None = None,
    ) -> ScopedView:
        """Return only what live consent and an unexpired TTL permit.

        ``required_purposes`` narrows further, so an engine can take the view it
        needs rather than everything the customer has permitted — purpose
        limitation applied a second time, at the point of use.
        """
        as_of = as_of or date.today()

        values: dict[str, Any] = {}
        exclusions: list[Exclusion] = []
        used: set[Purpose] = set()

        for name, entry in self._values.get(customer_token, {}).items():
            purpose = entry.spec.purpose
            state = purpose_state(consent, customer_token, purpose, as_of=as_of)

            if state != "live":
                reason = "purpose_revoked" if state == "revoked" else "purpose_expired"
                exclusions.append(Exclusion(name, purpose.value, reason))
                continue
            if entry.expired(as_of):
                exclusions.append(Exclusion(name, purpose.value, "expired"))
                continue
            if required_purposes is not None and purpose not in required_purposes:
                continue

            values[name] = entry.value
            used.add(purpose)

        return ScopedView(
            values=values,
            exclusions=tuple(sorted(exclusions, key=lambda e: e.feature)),
            purposes_used=tuple(sorted(used, key=lambda p: p.value)),
        )

    def expiry_countdown(
        self, customer_token: str, *, as_of: date | None = None
    ) -> dict[str, int]:
        """Days remaining per feature — the visible countdown of report §9.1."""
        as_of = as_of or date.today()
        return {
            name: entry.days_remaining(as_of)
            for name, entry in self._values.get(customer_token, {}).items()
        }

    def forget(self, customer_token: str) -> int:
        """Erasure (report §9.1).

        Removes stored feature values for a customer. The model exclusion list
        that accompanies a full erasure request — so the customer's influence
        leaves trained models too — is the machine-unlearning item on the
        roadmap (report §13.1) and is not implemented here.
        """
        return len(self._values.pop(customer_token, {}))

    def known_customers(self) -> tuple[str, ...]:
        return tuple(self._values)


DEFAULT_STORE = FeatureStore()
