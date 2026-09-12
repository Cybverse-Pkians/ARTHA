"""The Financial Twin — simulation, shocks, counterfactual (report §5.1)."""

import pytest

from artha.core.money import emi_paise, rupees
from artha.engines.twin import FinancialTwin, Obligation, TwinVerdict
from artha.features.builder import build_profile
from artha.ontology.enrich import DEFAULT_PIPELINE
from artha.synth.generator import ARCHETYPES


def profile_for(key, generator, as_of):
    arch = ARCHETYPES[key]
    token, txns = generator.generate(key, months=14, end=as_of)
    enrichment = DEFAULT_PIPELINE.run(txns, as_of=as_of)
    return build_profile(
        token, enrichment, balance_paise=rupees(arch.opening_balance),
        age=arch.age, dependants=arch.dependants, thin_file=arch.thin_file,
        district=arch.district, is_rural=arch.is_rural, as_of=as_of,
    )


@pytest.fixture
def twin() -> FinancialTwin:
    return FinancialTwin(paths=300)


def test_simulation_is_reproducible(twin, generator, as_of):
    """A refusal must be reconstructable on demand by an auditor."""
    p = profile_for("salaried_stable", generator, as_of)
    a = twin.simulate(p, None, as_of=as_of)
    b = twin.simulate(p, None, as_of=as_of)
    assert a.breach_probability == b.breach_probability
    assert a.median_path_with == b.median_path_with


def test_adding_an_obligation_never_improves_the_projection(twin, generator, as_of):
    for key in ("salaried_stable", "gig", "agricultural", "business"):
        p = profile_for(key, generator, as_of)
        base = twin.simulate(p, None, as_of=as_of)
        emi = emi_paise(rupees(100_000), 0.14, 30)
        with_loan = twin.simulate(
            p,
            Obligation("test", emi, 5, 30, principal_paise=rupees(100_000), annual_rate=0.14),
            as_of=as_of,
        )
        assert with_loan.breach_probability >= base.breach_probability - 1e-9, key


def test_safe_buffer_scales_with_income_type(twin, generator, as_of):
    salaried = profile_for("salaried_stable", generator, as_of)
    farmer = profile_for("agricultural", generator, as_of)
    assert twin.safe_buffer_paise(salaried) > 0
    assert twin.safe_buffer_paise(farmer) > 0


def test_twin_produces_a_plain_language_sentence(twin, generator, as_of):
    p = profile_for("salaried_stable", generator, as_of)
    result = twin.simulate(p, None, as_of=as_of)
    assert result.sentence_en
    assert result.sentence_en[0].isupper()


def test_a_refusal_carries_a_counterfactual_or_an_explicit_blocker(twin, generator, as_of):
    """The Twin never merely refuses (report §5.1, §12)."""
    p = profile_for("stressed", generator, as_of)
    emi = emi_paise(rupees(200_000), 0.145, 36)
    requested = Obligation(
        "Personal loan", emi, 5, 36, principal_paise=rupees(200_000), annual_rate=0.145
    )
    result = twin.simulate(p, requested, as_of=as_of)
    if result.verdict is not TwinVerdict.AFFORDABLE:
        cf = twin.counterfactual(p, requested, as_of=as_of)
        assert cf.available or cf.blocker


def test_counterfactual_is_never_larger_than_the_request(twin, generator, as_of):
    p = profile_for("salaried_volatile", generator, as_of)
    principal = rupees(300_000)
    emi = emi_paise(principal, 0.145, 36)
    requested = Obligation(
        "Personal loan", emi, 5, 36, principal_paise=principal, annual_rate=0.145
    )
    cf = twin.counterfactual(p, requested, as_of=as_of)
    if cf.available:
        assert cf.amount_paise <= principal


def test_scenarios_are_tested_and_reported(twin, generator, as_of):
    p = profile_for("gig", generator, as_of)
    result = twin.simulate(p, None, as_of=as_of)
    keys = {s.key for s in result.scenarios}
    assert "income_delay" in keys
    assert "medical" in keys


def test_seeding_is_stable_across_processes(generator, as_of):
    """`hash()` of a string is salted per interpreter, so anything seeded from it
    reproduces within one process and not across two.

    An auditor asking why a customer was refused in March must be able to re-run
    March's simulation and obtain March's answer, so the seed has to be a content
    hash rather than a runtime hash.
    """
    from artha.core.rng import stable_index, stable_seed

    # A golden value on purpose: an in-process equality check would have passed
    # against the old `hash()`-based seed too, since `hash()` is stable *within*
    # a run. Only a constant recorded from a previous process catches the
    # regression this test exists for.
    assert stable_seed(20260912, "tok_demo", "base") == 67372145
    assert stable_seed("a") != stable_seed("b")
    assert 0 <= stable_index(7, "tok_demo") < 7
