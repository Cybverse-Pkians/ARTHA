"""Shared application state for the API.

One :class:`ArthaEngine` per process, plus a demo bootstrap that seeds the
synthetic archetypes so the banker console has something to show on a cold
start. The bootstrap is explicitly labelled as synthetic everywhere it surfaces
— report §11.2 requires that illustrative figures are never presented as
measured results, and a dashboard is the easiest place to blur that line.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

from ..audit.log import AuditLog, RecordType
from ..consent.manager import ConsentManager
from ..core.money import rupees
from ..core.types import Channel, RecoveryState, Transaction
from ..engines.twin import FinancialTwin
from ..features.store import FeatureStore
from ..gate.conduct import EmpathyCalendar, NudgeBudget
from ..gate.fairness import FairnessMonitor
from ..gate.recovery import RecoveryMachine
from ..journey.session import JourneyStore
from ..llm.capability import CapabilityBroker
from ..llm.firewall import AIFirewall
from ..orchestrator import ArthaEngine
from ..synth.generator import ARCHETYPES, SyntheticGenerator

DEMO_AS_OF = date(2026, 9, 12)


@lru_cache(maxsize=1)
def get_engine() -> ArthaEngine:
    """The one engine this process decides with.

    Every stateful collaborator is constructed here rather than taken from the
    module-level defaults. Those defaults are shared singletons, so an engine
    that used them would carry nudge budgets and Recovery-Mode records that
    outlive it — and ``/banker/demo/reset``, which drops this cache to rebuild
    the portfolio, would then reset nothing at all.
    """
    engine = ArthaEngine(
        twin=FinancialTwin(),
        recovery=RecoveryMachine(),
        budget=NudgeBudget(),
        calendar=EmpathyCalendar(),
        fairness=FairnessMonitor(),
        consent=ConsentManager(),
        audit=AuditLog(),
        features=FeatureStore(),
    )
    _bootstrap_demo(engine)
    return engine


@lru_cache(maxsize=1)
def get_journeys() -> JourneyStore:
    return JourneyStore()


@lru_cache(maxsize=1)
def get_firewall() -> AIFirewall:
    return AIFirewall()


@lru_cache(maxsize=1)
def get_broker() -> CapabilityBroker:
    return CapabilityBroker()


def _bootstrap_demo(engine: ArthaEngine) -> None:
    generator = SyntheticGenerator()
    for key, arch in ARCHETYPES.items():
        token, txns = generator.generate(key, months=14, end=DEMO_AS_OF)
        engine.consent.grant_defaults(token, as_of=DEMO_AS_OF)
        engine.ingest(
            token, txns, as_of=DEMO_AS_OF,
            balance_paise=rupees(arch.opening_balance),
            age=arch.age, dependants=arch.dependants, thin_file=arch.thin_file,
            district=arch.district, is_rural=arch.is_rural,
            has_term_cover=arch.has_term_cover, has_health_cover=arch.has_health_cover,
            tenure_with_bank_months=36,
            on_time_emi_streak=(0 if "arrears" in arch.tags else 14),
            gender=("F" if key == "thin_file_woman" else "M"),
        )
    _seed_active_recovery_plan(engine)


def _seed_active_recovery_plan(engine: ArthaEngine) -> None:
    """Put the restructured customer mid-plan rather than at its first day.

    Arrears alone cannot express "a plan granted earlier, honoured since": the
    restructured account is current under its new mandate, which is precisely
    why its classification reads standard. Recovery Mode is therefore seeded
    here, with the same evidence a real transition would carry, so the console
    shows a customer partway through stabilisation instead of one who entered
    Recovery Mode this morning.
    """
    token = DEMO_ARCHETYPE_TOKENS.get("recovery_restructured")
    if token is None or token not in engine._states:
        return

    granted = DEMO_AS_OF - timedelta(days=62)
    engine.recovery.transition(
        token, RecoveryState.RECOVERY,
        reason="Restructuring granted for borrower financial difficulty",
        evidence=(
            "Two instalments missed before the plan was granted.",
            f"Instalment reduced and moved to after income arrives, effective "
            f"{granted.isoformat()}.",
            "Four instalments honoured under the new mandate since; personalisation "
            "resumes once the plan has been honoured for 90 days.",
            "Treatment of restructuring granted for financial difficulty is a "
            "design hypothesis to be verified against the current RBI stressed-"
            "asset framework (report §11.2).",
        ),
        at=granted,
    )
    record = engine.recovery.get(token)
    record.plan_started = granted
    record.plan_honoured_since = granted
    engine.audit.append(
        RecordType.RECOVERY_TRANSITION, token,
        {
            "to_state": RecoveryState.RECOVERY.value,
            "trigger": "RESTRUCTURING_GRANTED",
            "plan_started": granted.isoformat(),
            "note": (
                "Demo seeding: a plan granted before the synthetic window opens, "
                "so the console can show an account partway through stabilisation. "
                "Illustrative only (report §11.2)."
            ),
        },
    )
    engine.invalidate(token)


def parse_transactions(customer_token: str, rows) -> list[Transaction]:
    out: list[Transaction] = []
    for r in rows:
        out.append(Transaction(
            txn_id=r.txn_id,
            customer_token=customer_token,
            ts=datetime.fromisoformat(r.ts),
            amount_paise=r.amount_paise,
            narration=r.narration,
            channel=Channel(r.channel) if r.channel in Channel.__members__ else Channel.UPI,
            balance_after_paise=r.balance_after_paise,
            counterparty_vpa=r.counterparty_vpa,
            counterparty_name=r.counterparty_name,
        ))
    return out


DEMO_ARCHETYPE_TOKENS = {key: f"tok_{key}" for key in ARCHETYPES}

# Demo presentation only. The engine deliberately knows nothing about
# archetypes — it holds a customer token and a transaction history, exactly as
# it would in a bank — so the human-readable label for a seeded customer lives
# here with the rest of the demo bootstrap rather than on the profile.
DEMO_LABELS: dict[str, str] = {
    f"tok_{key}": arch.label for key, arch in ARCHETYPES.items()
}
# Invented names for invented people. They live here, not on the profile, so
# the engine keeps deciding about a token and nothing downstream can start
# treating a name as a feature.
DEMO_NAMES: dict[str, str] = {
    f"tok_{key}": arch.display_name for key, arch in ARCHETYPES.items()
}
DEMO_TAGS: dict[str, tuple[str, ...]] = {
    f"tok_{key}": tuple(arch.tags) for key, arch in ARCHETYPES.items()
}
