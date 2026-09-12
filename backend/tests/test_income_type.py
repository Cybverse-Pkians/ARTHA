"""Income typing — the label that reconfigures every downstream model (§4.2)."""

import pytest

from artha.core.types import IncomeType
from artha.ontology.enrich import DEFAULT_PIPELINE
from artha.ontology.income_type import buffer_multiplier
from artha.synth.generator import ARCHETYPES


@pytest.mark.parametrize("key", sorted(ARCHETYPES))
def test_income_type_matches_the_labelled_archetype(key, generator, as_of):
    arch = ARCHETYPES[key]
    _, txns = generator.generate(key, months=14, end=as_of)
    result = DEFAULT_PIPELINE.run(txns, as_of=as_of)
    assert result.income.income_type is arch.expected_income_type, (
        f"{key}: got {result.income.income_type.value}, "
        f"expected {arch.expected_income_type.value}"
    )


def test_seasonal_is_distinguished_from_a_job_loss(generator, as_of):
    """Both show long income-less stretches; only one repeats.

    Report §11.3 names misclassifying seasonal income as irregular as a top
    limitation, because it denies credit to exactly the population the problem
    statement concerns.
    """
    _, txns = generator.generate("thin_file_woman", months=14, end=as_of)
    result = DEFAULT_PIPELINE.run(txns, as_of=as_of)
    assert result.income.income_type is IncomeType.SEASONAL
    assert result.income.features["income_runs"] >= 2


def test_human_override_wins_unconditionally(generator, as_of):
    """The correction path of report §5.1 is mandatory, not advisory."""
    _, txns = generator.generate("gig", months=14, end=as_of)
    result = DEFAULT_PIPELINE.run(
        txns, income_override=IncomeType.AGRICULTURAL, as_of=as_of
    )
    assert result.income.income_type is IncomeType.AGRICULTURAL
    assert result.income.method == "override"
    assert result.income.overridden


def test_buffer_widens_for_less_predictable_income():
    """A farmer between harvests needs more reserve than a salaried customer."""
    assert buffer_multiplier(IncomeType.AGRICULTURAL) > buffer_multiplier(IncomeType.GIG)
    assert buffer_multiplier(IncomeType.GIG) > buffer_multiplier(IncomeType.SALARIED_STABLE)


def test_assessed_income_is_not_inflated_by_harvest_clustering(generator, as_of):
    """Harvest payments thirty days apart look monthly to a periodicity detector.

    Annualising that series invents an income the customer does not have, and
    the Twin would then clear loans against it.
    """
    arch = ARCHETYPES["agricultural"]
    _, txns = generator.generate("agricultural", months=14, end=as_of)
    result = DEFAULT_PIPELINE.run(txns, as_of=as_of)
    stated_monthly = arch.monthly_income * 100
    assert result.monthly_income_paise < stated_monthly * 2.2
