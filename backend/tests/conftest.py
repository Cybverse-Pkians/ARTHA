"""Shared fixtures.

The synthetic generator (report §11.1) is the only data source in the test
suite. No real transaction data is used, and none should be.
"""

from __future__ import annotations

from datetime import date

import pytest

from artha.audit.log import AuditLog
from artha.consent.manager import ConsentManager
from artha.core.money import rupees
from artha.engines.twin import FinancialTwin
from artha.gate.conduct import EmpathyCalendar, NudgeBudget
from artha.gate.fairness import FairnessMonitor
from artha.gate.recovery import RecoveryMachine
from artha.orchestrator import ArthaEngine
from artha.synth.generator import ARCHETYPES, SyntheticGenerator

AS_OF = date(2026, 9, 12)


@pytest.fixture
def as_of() -> date:
    return AS_OF


@pytest.fixture
def generator() -> SyntheticGenerator:
    return SyntheticGenerator()


@pytest.fixture
def engine() -> ArthaEngine:
    """A fresh engine per test.

    Every collaborator is constructed explicitly rather than taken from the
    module-level defaults, so state cannot leak between tests — nudge budgets
    and Recovery-Mode records in particular are stateful and would otherwise
    make test order significant.
    """
    return ArthaEngine(
        twin=FinancialTwin(paths=300),
        recovery=RecoveryMachine(),
        budget=NudgeBudget(),
        calendar=EmpathyCalendar(),
        fairness=FairnessMonitor(),
        consent=ConsentManager(),
        audit=AuditLog(),
    )


@pytest.fixture
def ingest(engine, generator, as_of):
    """Ingest an archetype into the engine and return its token."""

    def _ingest(key: str, **overrides) -> str:
        arch = ARCHETYPES[key]
        token, txns = generator.generate(key, months=14, end=as_of)
        engine.consent.grant_defaults(token, as_of=as_of)
        kwargs = dict(
            balance_paise=rupees(arch.opening_balance),
            age=arch.age,
            dependants=arch.dependants,
            thin_file=arch.thin_file,
            district=arch.district,
            is_rural=arch.is_rural,
            has_term_cover=arch.has_term_cover,
            has_health_cover=arch.has_health_cover,
            tenure_with_bank_months=36,
            on_time_emi_streak=14,
        )
        kwargs.update(overrides)
        engine.ingest(token, txns, as_of=as_of, **kwargs)
        return token

    return _ingest
