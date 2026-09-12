"""Catalogue invariants, fail-closed eligibility, and offer sizing.

This file was committed empty in 284c228 and so has never run. It restores the
cover its commit message claimed: that a broken eligibility predicate denies
rather than approves, that every rule carries a name a rejected customer can be
shown, and that a Twin-reduced offer reports itself as reduced.
"""

from __future__ import annotations

import pytest

from artha.core.money import rupees
from artha.core.types import ProductFamily
from artha.products.catalogue import (
    CATALOGUE,
    EligibilityRule,
    Product,
    ProductOffer,
    by_family,
)


# --- fail-closed ------------------------------------------------------------

def test_a_rule_whose_predicate_raises_denies_rather_than_approves():
    """Report §5.1 / ELG-001. A broken check must never hand out an offer."""
    exploding = EligibilityRule(
        "boom", "Predicate raises", lambda p: 1 / 0,  # ZeroDivisionError
    )
    assert exploding.check(object()) is False


def test_a_rule_reading_a_missing_attribute_fails_closed():
    missing = EligibilityRule(
        "needs_age", "Reads an attribute the profile does not have",
        lambda p: p.age >= 18,
    )
    assert missing.check(object()) is False


def test_a_rule_returning_a_truthy_non_bool_is_coerced():
    truthy = EligibilityRule("truthy", "Returns 1", lambda p: 1)
    assert truthy.check(object()) is True


# --- every rule is nameable -------------------------------------------------

def test_every_catalogue_rule_carries_a_name_and_description():
    """An unnamed lambda cannot be shown to a rejected customer."""
    for product in CATALOGUE:
        for rule in product.rules:
            assert rule.name, f"{product.product_id} has an unnamed rule"
            assert rule.description, f"{product.product_id}:{rule.name} has no description"


def test_failing_rules_names_every_rule_a_bare_profile_cannot_satisfy():
    """A profile with no attributes fails closed on every rule it touches."""
    for product in CATALOGUE:
        if not product.rules:
            continue
        failing = product.failing_rules(object())
        assert len(failing) == len(product.rules)
        assert all(r.name for r in failing)


# --- catalogue invariants ---------------------------------------------------

def test_product_ids_are_unique():
    ids = [p.product_id for p in CATALOGUE]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("product", CATALOGUE, ids=lambda p: p.product_id)
def test_product_amount_and_rate_bounds_are_coherent(product: Product):
    assert product.min_amount_paise > 0
    assert product.max_amount_paise >= product.min_amount_paise
    assert product.annual_rate >= 0.0
    if product.requires_monthly_repayment:
        assert product.tenures, f"{product.product_id} repays monthly but has no tenure"
        assert all(t > 0 for t in product.tenures)


def test_by_family_returns_only_that_family_and_partitions_the_catalogue():
    seen = 0
    for family in ProductFamily:
        products = by_family(family)
        assert all(p.family is family for p in products)
        seen += len(products)
    assert seen == len(CATALOGUE)


# --- offer sizing -----------------------------------------------------------

def _offer(product: Product, *, amount: int, eligible: int) -> ProductOffer:
    return ProductOffer(
        product=product,
        amount_paise=amount,
        eligible_amount_paise=eligible,
        tenure_months=24,
        emi_paise=rupees(5_000),
        day_of_month=5,
        annual_rate=product.annual_rate,
        total_interest_paise=rupees(10_000),
    )


def test_an_offer_sized_below_eligibility_reports_itself_as_reduced():
    """Report §5.2 — the customer is told both figures, so both are retained."""
    product = next(p for p in CATALOGUE if p.family is ProductFamily.LOAN)
    offer = _offer(product, amount=rupees(250_000), eligible=rupees(500_000))
    assert offer.is_reduced_from_eligibility is True
    assert offer.eligible_amount_paise > offer.amount_paise


def test_an_offer_at_full_eligibility_is_not_reported_as_reduced():
    product = next(p for p in CATALOGUE if p.family is ProductFamily.LOAN)
    offer = _offer(product, amount=rupees(500_000), eligible=rupees(500_000))
    assert offer.is_reduced_from_eligibility is False
