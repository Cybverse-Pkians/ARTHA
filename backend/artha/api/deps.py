"""Shared application state for the API.

One :class:`ArthaEngine` per process, plus a demo bootstrap that seeds the
synthetic archetypes so the banker console has something to show on a cold
start. The bootstrap is explicitly labelled as synthetic everywhere it surfaces
— report §11.2 requires that illustrative figures are never presented as
measured results, and a dashboard is the easiest place to blur that line.
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from functools import lru_cache

from ..core.money import rupees
from ..core.types import Channel, Transaction
from ..journey.session import JourneyStore
from ..llm.capability import CapabilityBroker
from ..llm.firewall import AIFirewall
from ..orchestrator import ArthaEngine
from ..synth.generator import ARCHETYPES, SyntheticGenerator

DEMO_AS_OF = date(2026, 9, 12)


@lru_cache(maxsize=1)
def get_engine() -> ArthaEngine:
    engine = ArthaEngine()
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


# The banker aggregates (queue, suppression, dual ledger) need a decision for
# every customer. Re-deciding on each page load re-ran the Twin across the whole
# book — about ninety seconds for the eleven archetypes — and appended a fresh
# decision record and fairness observation every time. Decisions are therefore
# kept per customer, and every route that changes a customer's inputs forgets
# that customer's entry. The lock also serialises engine.decide across threads.
_decisions: dict[str, object] = {}
_decisions_lock = threading.Lock()


def decide_cached(customer_token: str):
    with _decisions_lock:
        bundle = _decisions.get(customer_token)
        if bundle is None:
            bundle = get_engine().decide(customer_token, as_of=DEMO_AS_OF)
            _decisions[customer_token] = bundle
        return bundle


def decide_live(customer_token: str, **kwargs):
    """A what-if decision (requested product or amount, missed payment, as_of)."""
    with _decisions_lock:
        bundle = get_engine().decide(customer_token, **kwargs)
        # A what-if can move recovery state the cached bundle predates.
        _decisions.pop(customer_token, None)
        return bundle


def forget_decision(customer_token: str) -> None:
    with _decisions_lock:
        _decisions.pop(customer_token, None)


def warm_decisions() -> None:
    for token in list(get_engine()._states):
        decide_cached(token)


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
            tenure_with_bank_months=36, on_time_emi_streak=14,
            gender=("F" if key == "thin_file_woman" else "M"),
        )


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
