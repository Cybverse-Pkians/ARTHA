"""Consent manager and the privacy ledger.

Report §4.1, §6.6 and §9.1. Two responsibilities:

* decide, at inference time, whether a given purpose is live for a customer;
* record, for every nudge, exactly what data was used, what was explicitly *not*
  used, when the permission expires and how to revoke it.

The second is the privacy ledger. Naming what was refused is the part customers
find credible, and it is cheap to produce because the Gate already knows which
purposes it excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from .purposes import REGISTRY, Purpose


@dataclass(frozen=True)
class ConsentGrant:
    purpose: Purpose
    granted_at: date
    expires_at: date
    source: str = "app"                     # app | ivr | branch | aa_artefact
    revoked: bool = False

    def live(self, as_of: date | None = None) -> bool:
        as_of = as_of or date.today()
        return not self.revoked and as_of <= self.expires_at

    def days_remaining(self, as_of: date | None = None) -> int:
        as_of = as_of or date.today()
        return max((self.expires_at - as_of).days, 0)


@dataclass
class ConsentManager:
    """Per-customer purpose state.

    Kept deliberately simple: a grant is live or it is not, and an engine that
    needs a dead purpose does not run. There is no "soft" consent state, because
    a soft state is one that gets resolved in the bank's favour under pressure.
    """

    grants: dict[str, dict[Purpose, ConsentGrant]] = field(default_factory=dict)

    def grant(
        self,
        customer_token: str,
        purpose: Purpose,
        *,
        as_of: date | None = None,
        ttl_days: int | None = None,
        source: str = "app",
    ) -> ConsentGrant:
        as_of = as_of or date.today()
        spec = REGISTRY[purpose]
        grant = ConsentGrant(
            purpose=purpose,
            granted_at=as_of,
            expires_at=as_of + timedelta(days=ttl_days or spec.default_ttl_days),
            source=source,
        )
        self.grants.setdefault(customer_token, {})[purpose] = grant
        return grant

    def grant_defaults(self, customer_token: str, *, as_of: date | None = None) -> None:
        """Grant the purposes a customer consents to at onboarding."""
        for purpose in (
            Purpose.ACCOUNT_SERVICING, Purpose.FRAUD_MONITORING,
            Purpose.AFFORDABILITY_ASSESSMENT, Purpose.PRODUCT_RECOMMENDATION,
            Purpose.STRESS_EARLY_WARNING, Purpose.MARKETING_CONTACT,
        ):
            self.grant(customer_token, purpose, as_of=as_of)

    def revoke(self, customer_token: str, purpose: Purpose) -> bool:
        spec = REGISTRY[purpose]
        if not spec.withdrawable:
            return False
        existing = self.grants.get(customer_token, {}).get(purpose)
        if not existing:
            return False
        self.grants[customer_token][purpose] = ConsentGrant(
            purpose=purpose, granted_at=existing.granted_at,
            expires_at=existing.expires_at, source=existing.source, revoked=True,
        )
        return True

    def is_live(self, customer_token: str, purpose: Purpose, *, as_of: date | None = None) -> bool:
        grant = self.grants.get(customer_token, {}).get(purpose)
        return bool(grant and grant.live(as_of))

    def live_purposes(self, customer_token: str, *, as_of: date | None = None) -> set[Purpose]:
        return {
            p for p, g in self.grants.get(customer_token, {}).items() if g.live(as_of)
        }

    def excluded_purposes(self, customer_token: str, *, as_of: date | None = None) -> set[Purpose]:
        return set(Purpose) - self.live_purposes(customer_token, as_of=as_of)


@dataclass(frozen=True)
class PrivacyLedgerEntry:
    """One nudge, one ledger line (report §6.6)."""

    decision_id: str
    customer_token: str
    at: str
    purposes_used: tuple[str, ...]
    purposes_not_used: tuple[str, ...]
    expiry_countdown_days: dict[str, int]
    revocation_hint: str

    def render(self, lang: str = "en") -> dict:
        used = [REGISTRY[Purpose(p)].label(lang) for p in self.purposes_used]
        not_used = [REGISTRY[Purpose(p)].label(lang) for p in self.purposes_not_used]
        return {
            "used": used,
            "not_used": not_used,
            "expiry_days": self.expiry_countdown_days,
            "revoke": self.revocation_hint,
        }


def build_ledger_entry(
    manager: ConsentManager,
    *,
    decision_id: str,
    customer_token: str,
    purposes_used: set[Purpose],
    as_of: date | None = None,
    lang: str = "en",
) -> PrivacyLedgerEntry:
    as_of = as_of or date.today()
    live = manager.live_purposes(customer_token, as_of=as_of)
    countdown = {
        p.value: manager.grants[customer_token][p].days_remaining(as_of)
        for p in live
        if customer_token in manager.grants and p in manager.grants[customer_token]
    }
    return PrivacyLedgerEntry(
        decision_id=decision_id,
        customer_token=customer_token,
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        purposes_used=tuple(sorted(p.value for p in purposes_used)),
        purposes_not_used=tuple(sorted(p.value for p in (set(Purpose) - purposes_used))),
        expiry_countdown_days=countdown,
        revocation_hint=(
            "एक टैप में बंद करें" if lang == "hi" else "Turn this off in one tap"
        ),
    )


DEFAULT_MANAGER = ConsentManager()


def purpose_state(
    manager: ConsentManager,
    customer_token: str,
    purpose: Purpose,
    *,
    as_of: date | None = None,
) -> str:
    """Why a purpose is unavailable, not merely that it is.

    "live" | "revoked" | "expired" | "never_granted".

    The distinction is customer-facing, not bookkeeping. A privacy ledger that
    says "you turned this off" when the permission actually lapsed is telling
    the customer something untrue about their own choices, and the remedy
    differs: a lapsed permission can simply be renewed.
    """
    as_of = as_of or date.today()
    grant = manager.grants.get(customer_token, {}).get(purpose)
    if grant is None:
        return "never_granted"
    if grant.revoked:
        return "revoked"
    if as_of > grant.expires_at:
        return "expired"
    return "live"
