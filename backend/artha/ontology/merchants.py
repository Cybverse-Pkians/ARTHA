"""Indian merchant taxonomy and resolution.

Report §7.1 justifies a dictionary plus fuzzy match rather than a language
model: the merchant vocabulary a retail bank actually sees is finite and
curatable, and a curated dictionary is cheaper, faster, deterministic and
auditable. A regulator can be shown the table. It cannot be shown a prompt.

The seed list below is representative rather than exhaustive; in deployment it
is maintained as data, not code, and versioned with the model registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..core.types import Category, Merchant

# --- seed taxonomy ----------------------------------------------------------
# (merchant_id, display name, category, aliases, high-cost lender flag)
_SEED: list[tuple[str, str, Category, tuple[str, ...], bool]] = [
    # Groceries / retail
    ("bigbazaar", "Big Bazaar", Category.GROCERIES, ("bigbazar", "futureretail"), False),
    ("dmart", "DMart", Category.GROCERIES, ("avenuesupermarts", "d mart"), False),
    ("reliancefresh", "Reliance Fresh", Category.GROCERIES, ("reliance retail", "reliancesmart"), False),
    ("blinkit", "Blinkit", Category.GROCERIES, ("grofers",), False),
    ("zepto", "Zepto", Category.GROCERIES, (), False),
    ("bigbasket", "BigBasket", Category.GROCERIES, ("bbdaily", "innovative retail"), False),
    ("kirana", "Neighbourhood kirana", Category.GROCERIES, ("kirana", "general store", "provision"), False),

    # Dining
    ("swiggy", "Swiggy", Category.DINING, ("bundl technologies",), False),
    ("zomato", "Zomato", Category.DINING, ("eternal ltd",), False),
    ("dominos", "Domino's", Category.DINING, ("jubilant foodworks",), False),
    ("mcdonalds", "McDonald's", Category.DINING, ("hardcastle",), False),
    ("cafecoffeeday", "Cafe Coffee Day", Category.DINING, ("ccd",), False),

    # Fuel / transport
    ("iocl", "Indian Oil", Category.FUEL, ("indianoil", "indian oil", "ioc petrol"), False),
    ("hpcl", "HP Petrol Pump", Category.FUEL, ("hindustan petroleum", "hp petrol"), False),
    ("bpcl", "Bharat Petroleum", Category.FUEL, ("bharatpetroleum",), False),
    ("ola", "Ola", Category.TRANSPORT, ("anitechnologies", "olacabs"), False),
    ("uber", "Uber", Category.TRANSPORT, ("uberindia",), False),
    ("irctc", "IRCTC", Category.TRAVEL, ("indianrailways", "irctc ltd"), False),
    ("rapido", "Rapido", Category.TRANSPORT, ("roppen",), False),

    # Utilities / telecom
    ("adanielectricity", "Adani Electricity", Category.UTILITIES, ("adani elec",), False),
    ("mseb", "MSEDCL", Category.UTILITIES, ("mahadiscom", "msedcl"), False),
    ("bses", "BSES", Category.UTILITIES, ("bsesdelhi", "bses rajdhani"), False),
    ("torrentpower", "Torrent Power", Category.UTILITIES, (), False),
    ("jio", "Jio", Category.TELECOM, ("reliancejio", "jio recharge"), False),
    ("airtel", "Airtel", Category.TELECOM, ("bhartiairtel", "airtel recharge"), False),
    ("vodafoneidea", "Vi", Category.TELECOM, ("vodafone", "idea cellular", "vi recharge"), False),
    ("bsnl", "BSNL", Category.TELECOM, (), False),
    ("indane", "Indane Gas", Category.UTILITIES, ("hpgas", "bharatgas", "lpg"), False),

    # Subscriptions
    ("netflix", "Netflix", Category.SUBSCRIPTION, (), False),
    ("hotstar", "JioHotstar", Category.SUBSCRIPTION, ("disneyhotstar", "jiocinema"), False),
    ("spotify", "Spotify", Category.SUBSCRIPTION, (), False),
    ("primevideo", "Amazon Prime", Category.SUBSCRIPTION, ("amazonprime",), False),

    # Health
    ("apollo", "Apollo Pharmacy", Category.PHARMACY, ("apollopharmacy", "apollo hosp"), False),
    ("medplus", "MedPlus", Category.PHARMACY, (), False),
    ("pharmeasy", "PharmEasy", Category.PHARMACY, ("axelia", "threpsi"), False),
    ("1mg", "Tata 1mg", Category.PHARMACY, ("tata1mg", "onemg"), False),
    ("drlalpathlabs", "Dr Lal PathLabs", Category.HEALTHCARE, ("lalpathlabs", "pathlabs"), False),
    ("thyrocare", "Thyrocare", Category.HEALTHCARE, (), False),
    ("fortis", "Fortis Hospital", Category.HEALTHCARE, (), False),
    ("maxhealthcare", "Max Healthcare", Category.HEALTHCARE, ("maxhosp",), False),

    # Education
    ("byjus", "BYJU'S", Category.EDUCATION, ("thinkandlearn",), False),
    ("unacademy", "Unacademy", Category.EDUCATION, ("sorting hat",), False),
    ("vidyalaya", "School fees", Category.EDUCATION, ("vidyalaya", "school fee", "vidya mandir"), False),

    # Apparel / commerce
    ("amazon", "Amazon", Category.APPAREL, ("amazonpay", "amzn", "amazon seller"), False),
    ("flipkart", "Flipkart", Category.APPAREL, ("fkrt", "flipkart internet"), False),
    ("myntra", "Myntra", Category.APPAREL, ("myntra designs",), False),
    ("meesho", "Meesho", Category.APPAREL, ("fashnear",), False),

    # Agri inputs
    ("iffco", "IFFCO", Category.AGRI_INPUT, ("iffco bazar", "krishi seva"), False),
    ("krishikendra", "Krishi Kendra", Category.AGRI_INPUT, ("krishi", "beej bhandar", "agri seva"), False),
    ("mandi", "Mandi / APMC", Category.AGRI_PROCEEDS, ("apmc", "mandi samiti", "krishi upaj"), False),

    # Investment / savings
    ("zerodha", "Zerodha", Category.INVESTMENT_OUT, ("zerodha broking",), False),
    ("groww", "Groww", Category.INVESTMENT_OUT, ("nextbillion",), False),
    ("nps", "NPS", Category.INVESTMENT_OUT, ("nsdl nps", "pension fund"), False),
    ("sipmf", "Mutual fund SIP", Category.INVESTMENT_OUT, ("bse starmf", "nse mfss", "sip mandate"), False),

    # Insurance
    ("licindia", "LIC", Category.INSURANCE_PREMIUM, ("lic of india", "licofindia"), False),
    ("hdfclife", "HDFC Life", Category.INSURANCE_PREMIUM, (), False),
    ("starhealth", "Star Health", Category.INSURANCE_PREMIUM, (), False),
    ("newindiaassurance", "New India Assurance", Category.INSURANCE_PREMIUM, ("niacl",), False),

    # High-cost credit — a §6.1 trigger, not merely a category
    ("kreditbee", "KreditBee", Category.HIGH_COST_CREDIT, ("finnovation", "krazybee"), True),
    ("truebalance", "True Balance", Category.HIGH_COST_CREDIT, (), True),
    ("moneyview", "Moneyview", Category.HIGH_COST_CREDIT, ("whizdm",), True),
    ("navi", "Navi", Category.HIGH_COST_CREDIT, ("chaitanya india",), True),
    ("cashe", "CASHe", Category.HIGH_COST_CREDIT, ("bhanix",), True),
    ("simpl", "Simpl", Category.HIGH_COST_CREDIT, ("getsimpl",), True),
    ("lazypay", "LazyPay", Category.HIGH_COST_CREDIT, ("pil lazypay",), True),
    ("slice", "Slice", Category.HIGH_COST_CREDIT, ("garagepreneurs",), True),

    # Gambling — never a product trigger; relevant to the willingness split (§6.3)
    ("dream11", "Dream11", Category.GAMBLING, ("sporta technologies",), False),
    ("mpl", "MPL", Category.GAMBLING, ("galactus funware",), False),
    ("rummycircle", "RummyCircle", Category.GAMBLING, ("games24x7",), False),
]


@dataclass(frozen=True)
class MerchantMatch:
    merchant: Merchant
    confidence: float
    matched_on: str


class MerchantResolver:
    """Exact-alias lookup first, fuzzy fallback second.

    Fuzzy matching uses :mod:`difflib` from the standard library. That is a
    deliberate choice — an extra dependency for string similarity is not worth
    it at this vocabulary size, and stdlib behaviour is stable across the
    versions a bank will actually run.
    """

    def __init__(self, seed: list | None = None, fuzzy_threshold: float = 0.86) -> None:
        self.fuzzy_threshold = fuzzy_threshold
        self._by_id: dict[str, Merchant] = {}
        self._alias_index: dict[str, str] = {}

        for mid, name, cat, aliases, high_cost in (seed or _SEED):
            merchant = Merchant(
                merchant_id=mid,
                display_name=name,
                category=cat,
                is_high_cost_lender=high_cost,
            )
            self._by_id[mid] = merchant
            for alias in (mid, name, *aliases):
                self._alias_index[_norm(alias)] = mid

    def resolve(self, token: str) -> MerchantMatch | None:
        key = _norm(token)
        if not key:
            return None

        if key in self._alias_index:
            return MerchantMatch(self._by_id[self._alias_index[key]], 1.0, "exact")

        # Containment: UPI handles routinely embed the brand ("swiggystores").
        for alias, mid in self._alias_index.items():
            if len(alias) >= 4 and alias in key:
                return MerchantMatch(self._by_id[mid], 0.94, "contains")

        best_id, best_score = None, 0.0
        for alias, mid in self._alias_index.items():
            if abs(len(alias) - len(key)) > 6:
                continue
            score = SequenceMatcher(None, alias, key).ratio()
            if score > best_score:
                best_id, best_score = mid, score

        if best_id and best_score >= self.fuzzy_threshold:
            return MerchantMatch(self._by_id[best_id], round(best_score, 3), "fuzzy")
        return None

    def get(self, merchant_id: str) -> Merchant | None:
        return self._by_id.get(merchant_id)

    @property
    def high_cost_lender_ids(self) -> frozenset[str]:
        return frozenset(m.merchant_id for m in self._by_id.values() if m.is_high_cost_lender)


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").strip()


DEFAULT_RESOLVER = MerchantResolver()
