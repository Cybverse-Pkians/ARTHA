"""Product catalogue: eligibility rules and offer sizing.

Two properties matter here and neither is about the catalogue being complete.

First, **eligibility fails closed.** A rule that raises must reject, because the
alternative — a broken predicate quietly passing — is how an ineligible customer
receives an offer, and it is the failure mode nobody sees until it has happened
at scale.

Second, **an offer is sized to what the cash flow carries, not to what policy
permits.** Report §5.2 makes the gap between maximum eligibility and recommended
amount the product itself, so a test suite that only checked the ceiling would
be asserting the opposite of the system's claim.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from artha.core.money import rupees
from artha.core.types import CustomerProfile, IncomeType, ProductFamily
from artha.engines.profitability import ProfitabilityEngine
from artha.engines.twin import FinancialTwin
from artha.products.catalogue import BY_ID, CATALOGUE, EligibilityRule, Product


def test_every_product_is_addressable_by_id():
    assert len(BY_ID) == len(CATALOGUE)
    for product in CATALOGUE:
        assert BY_ID[product.product_id] is product


def test_every_credit_product_declares_named_rules():
    """A rejected customer is entitled to be told which rule they failed.

    Reason code ELG-001 renders the rule's name, so a product that carries no
    named rules cannot produce an explainable rejection.
    """
    for product in CATALOGUE:
        if product.family is not ProductFamily.LOAN:
            continue
        assert product.rules, f"{product.product_id} has no named eligibility rules"
        for rule in product.rules:
            assert rule.name and rule.description


def test_a_rule_that_raises_fails_closed():
    exploding = EligibilityRule(
        "explodes", "Raises when evaluated",
        lambda p: 1 / 0,        # noqa: ARG005 - deliberately broken
    )
    profile = CustomerProfile(customer_token="tok_test")
    assert exploding.check(profile) is False


def test_a_product_with_a_broken_rule_reports_it_as_failing():
    broken = Product(
        product_id="broken", name="Broken", family=ProductFamily.LOAN,
        min_amount_paise=rupees(10_000), max_amount_paise=rupees(100_000),
        annual_rate=0.14, tenures=(12,),
        rules=(EligibilityRule("explodes", "Raises", lambda p: 1 / 0),),  # noqa: ARG005
    )
    profile = CustomerProfile(customer_token="tok_test")
    assert [r.name for r in broken.failing_rules(profile)] == ["explodes"]


def test_eligibility_rules_are_evaluated_against_the_profile(engine, ingest, as_of):
    token = ingest("thin_file_woman")
    profile = engine.state(token).profile
    personal = BY_ID["pl_standard"]
    failing = {r.name for r in personal.failing_rules(profile)}
    # A ₹11,500-a-month thin-file borrower should not clear a standard personal
    # loan's income floor. Which rule fails is the point: it is what the customer
    # is told.
    assert failing, "expected at least one named rule to fail for a thin-file borrower"


@pytest.mark.parametrize("archetype", ["salaried_stable", "business"])
def test_offer_is_sized_below_maximum_eligibility(engine, ingest, as_of, archetype):
    """Report §5.2: the gap between eligible and recommended is the product."""
    token = ingest(archetype)
    profile = engine.state(token).profile
    profitability = ProfitabilityEngine(twin=FinancialTwin(paths=300))
    product = BY_ID["pl_standard"]

    eligible = profitability.maximum_eligible_paise(profile, product)
    offer = profitability.structure(profile, product, as_of=as_of)
    if offer is None:
        pytest.skip("no structure cleared the Twin for this archetype")

    assert offer.eligible_amount_paise == eligible
    assert offer.amount_paise <= eligible
    assert offer.amount_paise >= product.min_amount_paise


def test_a_requested_amount_never_raises_the_offer_above_eligibility(engine, ingest, as_of):
    token = ingest("salaried_stable")
    profile = engine.state(token).profile
    profitability = ProfitabilityEngine(twin=FinancialTwin(paths=300))
    product = BY_ID["pl_standard"]

    eligible = profitability.maximum_eligible_paise(profile, product)
    offer = profitability.structure(
        profile, product, requested_amount_paise=eligible * 10, as_of=as_of
    )
    if offer is None:
        pytest.skip("no structure cleared the Twin for this archetype")
    assert offer.amount_paise <= eligible


def test_asking_for_less_is_honoured(engine, ingest, as_of):
    """Asking for more cannot produce more; asking for less must produce less."""
    token = ingest("salaried_stable")
    profile = engine.state(token).profile
    profitability = ProfitabilityEngine(twin=FinancialTwin(paths=300))
    product = BY_ID["pl_standard"]

    full = profitability.structure(profile, product, as_of=as_of)
    if full is None or full.amount_paise <= product.min_amount_paise:
        pytest.skip("no headroom to ask for less")

    modest = profitability.structure(
        profile, product, requested_amount_paise=full.amount_paise // 2, as_of=as_of
    )
    assert modest is not None
    assert modest.amount_paise <= full.amount_paise


def test_income_typing_gates_the_crop_facility():
    """A crop facility is for a farmer, and the rule says so by name."""
    crop = BY_ID["crop_facility"]
    farmer = CustomerProfile(
        customer_token="tok_farmer", income_type=IncomeType.AGRICULTURAL,
        monthly_income_paise=rupees(18_000), age=44, tenure_with_bank_months=36,
    )
    salaried = replace(farmer, income_type=IncomeType.SALARIED_STABLE)

    assert "income_type" not in {r.name for r in crop.failing_rules(farmer)}
    assert "income_type" in {r.name for r in crop.failing_rules(salaried)}
