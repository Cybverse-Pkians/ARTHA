"""Money: Indian grouping, lakh/crore speech, EMI arithmetic."""

from artha.core.money import (
    emi_paise,
    format_inr,
    indian_group,
    rupees,
    spoken_inr,
    total_cost_paise,
)


def test_indian_digit_grouping():
    assert indian_group(100_000) == "1,00,000"
    assert indian_group(10_000_000) == "1,00,00,000"
    assert indian_group(1_000) == "1,000"
    assert indian_group(999) == "999"
    assert indian_group(-250_000) == "-2,50,000"


def test_format_inr():
    assert format_inr(rupees(250_000)) == "₹2,50,000"
    assert format_inr(rupees(1_00_00_000)) == "₹1,00,00,000"


def test_rupees_rounds_half_up():
    assert rupees(10.005) == 1001
    assert rupees("4050") == 405_000


def test_spoken_amounts_use_lakh_vocabulary():
    """₹1,00,000 is 'one lakh', never 'one hundred thousand' (report §6.2)."""
    assert spoken_inr(rupees(100_000), "en").phrase == "1 lakh rupees"
    assert "लाख" in spoken_inr(rupees(250_000), "hi").phrase
    assert "crore" in spoken_inr(rupees(1_00_00_000), "en").phrase


def test_emi_and_total_cost():
    principal = rupees(100_000)
    emi = emi_paise(principal, 0.14, 30)
    assert rupees(3_500) < emi < rupees(4_500)
    interest = total_cost_paise(emi, 30, principal)
    assert interest > 0
    # A longer tenure lowers the instalment and raises the total cost — the
    # trade-off the Key Fact Statement must state (report §9.3).
    longer = emi_paise(principal, 0.14, 60)
    assert longer < emi
    assert total_cost_paise(longer, 60, principal) > interest
