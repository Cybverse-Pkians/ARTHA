"""Purpose registry for the Digital Personal Data Protection Act, 2023.

Report §4.1 and §9.1. Purpose limitation is enforced in the data layer rather
than asserted in a policy document: every feature carries the consent purpose
that permits it, plus a time-to-live and a source. When a customer revokes a
purpose, the associated features are excluded **at inference time**.

The distinction matters. A policy document says the data will not be used; a
feature store that cannot return the feature means it *was* not used, and the
difference is visible in the decision log.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Purpose(str, Enum):
    ACCOUNT_SERVICING = "ACCOUNT_SERVICING"
    AFFORDABILITY_ASSESSMENT = "AFFORDABILITY_ASSESSMENT"
    PRODUCT_RECOMMENDATION = "PRODUCT_RECOMMENDATION"
    FRAUD_MONITORING = "FRAUD_MONITORING"
    STRESS_EARLY_WARNING = "STRESS_EARLY_WARNING"
    CREDIT_BUREAU_PULL = "CREDIT_BUREAU_PULL"
    AA_STATEMENT_PULL = "AA_STATEMENT_PULL"
    MARKETING_CONTACT = "MARKETING_CONTACT"


@dataclass(frozen=True)
class PurposeSpec:
    purpose: Purpose
    label_en: str
    label_hi: str
    default_ttl_days: int
    withdrawable: bool
    legal_basis: str

    def label(self, lang: str = "en") -> str:
        return self.label_hi if lang == "hi" else self.label_en


REGISTRY: dict[Purpose, PurposeSpec] = {
    Purpose.ACCOUNT_SERVICING: PurposeSpec(
        Purpose.ACCOUNT_SERVICING,
        "Running your account", "आपका खाता चलाने के लिए",
        default_ttl_days=3650, withdrawable=False,
        legal_basis="Necessary to provide the service the customer has asked for.",
    ),
    Purpose.AFFORDABILITY_ASSESSMENT: PurposeSpec(
        Purpose.AFFORDABILITY_ASSESSMENT,
        "Checking whether you can afford a product",
        "यह देखने के लिए कि आप कोई उत्पाद वहन कर सकते हैं या नहीं",
        default_ttl_days=180, withdrawable=True,
        legal_basis="Consent. Withdrawing this disables the Financial Twin for this customer.",
    ),
    Purpose.PRODUCT_RECOMMENDATION: PurposeSpec(
        Purpose.PRODUCT_RECOMMENDATION,
        "Suggesting products that suit you", "आपके लिए उपयुक्त उत्पाद सुझाने के लिए",
        default_ttl_days=180, withdrawable=True,
        legal_basis="Consent.",
    ),
    Purpose.FRAUD_MONITORING: PurposeSpec(
        Purpose.FRAUD_MONITORING,
        "Protecting your account from fraud", "आपके खाते को धोखाधड़ी से बचाने के लिए",
        default_ttl_days=3650, withdrawable=False,
        legal_basis="Legitimate use for prevention of fraud; not withdrawable.",
    ),
    Purpose.STRESS_EARLY_WARNING: PurposeSpec(
        Purpose.STRESS_EARLY_WARNING,
        "Spotting trouble early so we can help", "समय रहते परेशानी पहचानने के लिए",
        default_ttl_days=365, withdrawable=True,
        legal_basis="Consent. Detection for risk reporting continues under servicing.",
    ),
    Purpose.CREDIT_BUREAU_PULL: PurposeSpec(
        Purpose.CREDIT_BUREAU_PULL,
        "Looking at your credit record", "आपका क्रेडिट रिकॉर्ड देखने के लिए",
        default_ttl_days=30, withdrawable=True,
        legal_basis="Consent, per pull.",
    ),
    Purpose.AA_STATEMENT_PULL: PurposeSpec(
        Purpose.AA_STATEMENT_PULL,
        "Fetching statements from your other banks",
        "आपके दूसरे बैंकों से विवरण लाने के लिए",
        default_ttl_days=30, withdrawable=True,
        legal_basis="Account Aggregator consent artefact, time-bound with automatic expiry.",
    ),
    Purpose.MARKETING_CONTACT: PurposeSpec(
        Purpose.MARKETING_CONTACT,
        "Contacting you about offers", "ऑफ़र के बारे में आपसे संपर्क करने के लिए",
        default_ttl_days=365, withdrawable=True,
        legal_basis="Consent. Suppressed entirely in Recovery Mode regardless of consent.",
    ),
}

# Which purpose each engine requires. The Gate consults this before running an
# engine at all, so a revoked purpose removes a capability rather than merely
# filtering its output.
ENGINE_PURPOSES: dict[str, Purpose] = {
    "twin": Purpose.AFFORDABILITY_ASSESSMENT,
    "moment": Purpose.PRODUCT_RECOMMENDATION,
    "ranker": Purpose.PRODUCT_RECOMMENDATION,
    "profitability": Purpose.PRODUCT_RECOMMENDATION,
    "sentinel_fraud": Purpose.FRAUD_MONITORING,
    "sentinel_stress": Purpose.STRESS_EARLY_WARNING,
    "delivery": Purpose.MARKETING_CONTACT,
}
