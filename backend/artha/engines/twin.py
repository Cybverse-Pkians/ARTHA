"""The Financial Twin — a per-customer Monte-Carlo simulation of the next six
months of account balance, run **before** any product is displayed.

Report §5.1 and §12. Three properties make this the novel component rather than
merely the affordability component:

* It simulates *with and without* the candidate obligation, so the cost of the
  product is expressed as a change in the customer's own trajectory rather than
  as a ratio.
* It stress-tests that trajectory explicitly — a delayed income, a lost income
  month, a medical expense, a festival spike — instead of assuming the mean.
* It never merely refuses. A refusal always carries a counterfactual: the exact
  structure at which the product would become affordable.

The same output serves three purposes (§5.1): it is the affordability engine, it
is the customer-facing explanation, and it is the consent screen. Consent is
informed by construction rather than by disclosure.

Every figure produced here is illustrative in the sense of report §11.2 — it is
computed from the synthetic generator or from whatever transaction history is
supplied, and it is not a measured portfolio result.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

import numpy as np

from ..config import settings
from ..core.money import format_inr, spoken_inr
from ..core.rng import stable_seed
from ..core.types import (
    Category,
    CustomerProfile,
    Direction,
    IncomeType,
    RecurringSeries,
)
from ..ontology.income_type import buffer_multiplier

DAYS_PER_MONTH = 30.44

# Scenario key prefix for the stacked-shock runs. They share the caching and
# obligation arithmetic of the named shocks, but they are not one of them — a
# stacked run removes income events rather than applying a scenario.
_STACK_PREFIX = "stack"


class TwinVerdict(str, Enum):
    AFFORDABLE = "AFFORDABLE"        # base case and every tested shock clear the buffer
    FRAGILE = "FRAGILE"              # base clears; at least one shock breaches
    UNAFFORDABLE = "UNAFFORDABLE"    # base case itself breaches


@dataclass(frozen=True)
class Obligation:
    """A candidate obligation to test against the customer's trajectory."""

    label: str
    emi_paise: int
    day_of_month: int
    tenure_months: int
    first_due: date | None = None
    principal_paise: int = 0
    annual_rate: float = 0.0


@dataclass(frozen=True)
class Shock:
    key: str
    label: str
    customer_label: str            # how it is said aloud, in English; translated at render


SHOCKS: tuple[Shock, ...] = (
    Shock("income_delay", "Income delayed by 15 days", "one late salary"),
    Shock("missed_income", "One income cycle missed entirely", "one missed month of work"),
    Shock("medical", "Unplanned medical expense", "one medical emergency"),
    Shock("festival", "Festival spending spike", "one festival month"),
)


# The Twin's plain-language output, by case, in every language the customer app
# offers. Held as templates keyed by case rather than as a formatted string so
# the sentence can be rendered in the customer's language at request time —
# ``sentence_en`` stays on the result for the regulator trace, which is written
# once and must not move.
TWIN_SENTENCES: dict[str, dict[str, str]] = {
    "breach": {
        "en": "Your balance would fall below your safety buffer around {month}.",
        "hi": "{month} के आसपास आपका बैलेंस आपके सुरक्षा बफ़र से नीचे चला जाएगा।",
        "mr": "{month} च्या सुमारास तुमची शिल्लक सुरक्षा राखीवाच्या खाली जाईल.",
        "ta": "{month} வாக்கில் உங்கள் இருப்பு பாதுகாப்பு நிலைக்குக் கீழே செல்லும்.",
        "bn": "{month} নাগাদ আপনার ব্যালান্স নিরাপত্তা সঞ্চয়ের নিচে নেমে যাবে।",
    },
    "fragile": {
        "en": "You could manage this month to month, but not if there were {hint}.",
        "hi": "आप इसे महीने-दर-महीने संभाल लेंगे, लेकिन {hint} होने पर नहीं।",
        "mr": "तुम्ही हे महिन्या-महिन्याने पेलू शकाल, पण {hint} झाल्यास नाही.",
        "ta": "மாதம் மாதம் இதைச் சமாளிக்க முடியும், ஆனால் {hint} ஏற்பட்டால் முடியாது.",
        "bn": "মাসে মাসে আপনি এটা সামলাতে পারবেন, তবে {hint} হলে নয়।",
    },
    "absorbs_two": {
        "en": "You can absorb two late payments of income and still stay above your buffer.",
        "hi": "आप आमदनी में दो बार की देरी झेल सकते हैं और फिर भी अपने बफ़र से ऊपर रहेंगे।",
        "mr": "तुम्ही उत्पन्नात दोनदा उशीर पेलू शकता आणि तरीही राखीवाच्या वर राहाल.",
        "ta": "வருமானத்தில் இரண்டு தாமதங்களைத் தாங்கியும் உங்கள் பாதுகாப்பு நிலைக்கு மேலே இருப்பீர்கள்.",
        "bn": "আয়ে দুবার দেরি হলেও আপনি সামলাতে পারবেন এবং নিরাপত্তা সঞ্চয়ের উপরে থাকবেন।",
    },
    "absorbs_one": {
        "en": "You can absorb one delayed salary, but not two.",
        "hi": "आप एक बार की देरी झेल सकते हैं, दो बार की नहीं।",
        "mr": "तुम्ही एकदा उशीर पेलू शकता, दोनदा नाही.",
        "ta": "ஒரு தாமதமான சம்பளத்தைத் தாங்க முடியும், இரண்டை அல்ல.",
        "bn": "একবার বেতন দেরি হলে সামলাতে পারবেন, দুবার নয়।",
    },
    "no_room": {
        "en": "This stays within your buffer, but there is no room for a surprise.",
        "hi": "यह आपके बफ़र के भीतर रहता है, पर किसी अचानक ख़र्च की गुंजाइश नहीं है।",
        "mr": "हे तुमच्या राखीवाच्या आत राहते, पण अनपेक्षित खर्चाला जागा नाही.",
        "ta": "இது உங்கள் பாதுகாப்பு நிலைக்குள் இருக்கிறது, ஆனால் எதிர்பாராத செலவுக்கு இடமில்லை.",
        "bn": "এটি আপনার নিরাপত্তা সঞ্চয়ের মধ্যেই থাকে, তবে অপ্রত্যাশিত খরচের জায়গা নেই।",
    },
}

# How each shock is named aloud. The English strings match the ``customer_label``
# on SHOCKS; the rest are the same phrase in the other four languages.
SHOCK_PHRASES: dict[str, dict[str, str]] = {
    "income_delay": {
        "en": "one late salary", "hi": "एक बार वेतन देर से आना",
        "mr": "एकदा पगार उशिरा येणे", "ta": "ஒரு முறை சம்பளம் தாமதமாவது",
        "bn": "একবার বেতন দেরিতে আসা",
    },
    "missed_income": {
        "en": "one missed month of work", "hi": "एक महीने का काम छूट जाना",
        "mr": "एक महिन्याचे काम चुकणे", "ta": "ஒரு மாத வேலை தவறுவது",
        "bn": "এক মাসের কাজ ফসকে যাওয়া",
    },
    "medical": {
        "en": "one medical emergency", "hi": "एक चिकित्सा आपात स्थिति",
        "mr": "एक वैद्यकीय आणीबाणी", "ta": "ஒரு மருத்துவ அவசரம்",
        "bn": "একটি চিকিৎসা জরুরি অবস্থা",
    },
    "festival": {
        "en": "one festival month", "hi": "एक त्योहार का महीना",
        "mr": "एक सणाचा महिना", "ta": "ஒரு பண்டிகை மாதம்",
        "bn": "একটি উৎসবের মাস",
    },
    "unexpected": {
        "en": "an unexpected expense", "hi": "कोई अचानक ख़र्च",
        "mr": "अनपेक्षित खर्च", "ta": "எதிர்பாராத செலவு",
        "bn": "অপ্রত্যাশিত খরচ",
    },
}

_MONTHS: dict[str, tuple[str, ...]] = {
    "en": ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"),
    "hi": ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
           "जुलाई", "अगस्त", "सितंबर", "अक्तूबर", "नवंबर", "दिसंबर"),
    "mr": ("जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून",
           "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"),
    "ta": ("ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்",
           "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"),
    "bn": ("জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
           "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"),
}


def twin_sentence(key: str, params: dict[str, str], lang: str = "en") -> str:
    """Render the Twin's plain-language verdict in one language."""
    case = TWIN_SENTENCES.get(key) or TWIN_SENTENCES["no_room"]
    template = case.get(lang) or case["en"]
    resolved = dict(params)
    if "month_index" in resolved:
        months = _MONTHS.get(lang) or _MONTHS["en"]
        resolved["month"] = months[int(resolved["month_index"]) - 1]
    if "shock" in resolved:
        phrases = SHOCK_PHRASES.get(resolved["shock"]) or SHOCK_PHRASES["unexpected"]
        resolved["hint"] = phrases.get(lang) or phrases["en"]
    try:
        return template.format(**resolved)
    except (KeyError, IndexError):
        return (TWIN_SENTENCES["no_room"].get(lang) or TWIN_SENTENCES["no_room"]["en"])


@dataclass(frozen=True)
class ScenarioResult:
    key: str
    label: str
    breach_probability: float
    min_balance_p05_paise: int
    first_breach_day: int | None
    passed: bool


@dataclass(frozen=True)
class TwinResult:
    """The Twin's complete output for one candidate.

    ``median_path_with`` / ``median_path_without`` are what Figure 3 renders:
    the projected balance with and without the requested obligation. They are
    returned in full because the chart *is* the explanation, and a chart the
    customer cannot see is not consent.
    """

    verdict: TwinVerdict
    horizon_days: int
    safe_buffer_paise: int
    opening_balance_paise: int

    breach_probability: float
    min_balance_p05_paise: int
    first_breach_date: date | None

    baseline_breach_probability: float      # without the obligation
    resilience_score: float                 # 0–100
    shocks_absorbed: int
    scenarios: tuple[ScenarioResult, ...] = field(default_factory=tuple)

    median_path_with: tuple[int, ...] = field(default_factory=tuple)
    median_path_without: tuple[int, ...] = field(default_factory=tuple)
    p05_path_with: tuple[int, ...] = field(default_factory=tuple)
    p95_path_with: tuple[int, ...] = field(default_factory=tuple)

    sentence_en: str = ""
    # The same sentence as a case key plus parameters, so the surfaces can render
    # it in the customer's language without re-deriving which case applied.
    sentence_key: str = "no_room"
    sentence_params: dict[str, str] = field(default_factory=dict)
    paths: int = 0
    seed: int = 0

    @property
    def passed(self) -> bool:
        return self.verdict is TwinVerdict.AFFORDABLE

    @property
    def headroom_paise(self) -> int:
        return self.min_balance_p05_paise - self.safe_buffer_paise


@dataclass(frozen=True)
class Counterfactual:
    """The structure at which a declined product becomes affordable.

    The Twin never merely refuses (report §5.1, §12). When no structure clears,
    ``available`` is False and ``blocker`` explains which constraint is binding —
    which is itself more useful to the customer than a bare rejection.
    """

    available: bool
    amount_paise: int = 0
    tenure_months: int = 0
    emi_paise: int = 0
    day_of_month: int = 0
    resilience_score: float = 0.0
    blocker: str = ""


class FinancialTwin:
    """Monte-Carlo cash-flow simulator conditioned on detected income type.

    The seed is fixed by configuration, not by wall-clock time. A lending
    decision has to be reproducible on demand: an auditor asking why a customer
    was refused in March must be able to re-run March's simulation and obtain
    March's answer.
    """

    def __init__(
        self,
        *,
        horizon_days: int | None = None,
        paths: int | None = None,
        seed: int | None = None,
        breach_ceiling: float | None = None,
    ) -> None:
        self.horizon_days = horizon_days or settings.twin_horizon_days
        self.paths = paths or settings.twin_paths
        self.seed = seed if seed is not None else settings.twin_seed
        self.breach_ceiling = (
            breach_ceiling if breach_ceiling is not None else settings.breach_probability_ceiling
        )
        # Simulated balances *before* any candidate obligation, by (profile,
        # as_of, scenario). The draws are already deterministic in the seed, so
        # reusing them changes no result — it removes the repeated work of
        # redrawing the same numbers. That matters because the counterfactual
        # search re-simulates the customer once per bisection, and the customer
        # is the expensive half: only the obligation differs between trials.
        #
        # Deliberately small. Each entry is a paths x horizon matrix of floats,
        # and one customer's full search touches the base case, one entry per
        # shock and one per stacked-shock depth — which is what this holds.
        self._base_cache: dict[tuple, np.ndarray] = {}
        self._base_cache_limit = 12

    # -- public API ---------------------------------------------------------

    def simulate(
        self,
        profile: CustomerProfile,
        obligation: Obligation | None = None,
        *,
        as_of: date | None = None,
    ) -> TwinResult:
        as_of = as_of or date.today()
        safe_buffer = self.safe_buffer_paise(profile)

        without = self._run(profile, None, as_of, scenario=None)
        with_ob = self._run(profile, obligation, as_of, scenario=None) if obligation else without

        base_breach, first_breach_day, min_p05 = self._assess(with_ob, safe_buffer)
        baseline_breach, _, _ = self._assess(without, safe_buffer)

        scenarios: list[ScenarioResult] = []
        for shock in SHOCKS:
            if not self._shock_applies(shock, profile):
                continue
            paths = self._run(profile, obligation, as_of, scenario=shock.key)
            breach, breach_day, p05 = self._assess(paths, safe_buffer)
            scenarios.append(
                ScenarioResult(
                    key=shock.key,
                    label=shock.label,
                    breach_probability=round(breach, 4),
                    min_balance_p05_paise=int(p05),
                    first_breach_day=breach_day,
                    passed=breach <= self.breach_ceiling,
                )
            )

        if base_breach > self.breach_ceiling:
            verdict = TwinVerdict.UNAFFORDABLE
        elif any(not s.passed for s in scenarios):
            verdict = TwinVerdict.FRAGILE
        else:
            verdict = TwinVerdict.AFFORDABLE

        absorbed = self._shocks_absorbed(profile, obligation, as_of, safe_buffer)
        resilience = self._resilience(base_breach, scenarios, absorbed)
        sentence_key, sentence_params = self._sentence(
            verdict, absorbed, scenarios, first_breach_day, as_of
        )

        return TwinResult(
            verdict=verdict,
            horizon_days=self.horizon_days,
            safe_buffer_paise=safe_buffer,
            opening_balance_paise=profile.balance_paise,
            breach_probability=round(base_breach, 4),
            min_balance_p05_paise=int(min_p05),
            first_breach_date=(as_of + timedelta(days=first_breach_day)) if first_breach_day is not None else None,
            baseline_breach_probability=round(baseline_breach, 4),
            resilience_score=resilience,
            shocks_absorbed=absorbed,
            scenarios=tuple(scenarios),
            median_path_with=_quantile_path(with_ob, 0.50),
            median_path_without=_quantile_path(without, 0.50),
            p05_path_with=_quantile_path(with_ob, 0.05),
            p95_path_with=_quantile_path(with_ob, 0.95),
            sentence_en=twin_sentence(sentence_key, sentence_params, "en"),
            sentence_key=sentence_key,
            sentence_params=sentence_params,
            paths=self.paths,
            seed=self.seed,
        )

    def verdict_for(
        self,
        profile: CustomerProfile,
        obligation: Obligation | None,
        *,
        as_of: date | None = None,
        safe_buffer: int | None = None,
    ) -> TwinVerdict:
        """The verdict alone, for callers searching over candidate structures.

        Identical arithmetic to :meth:`simulate`, minus the two things a search
        never looks at: the percentile paths the chart renders, and the stacked
        shock depth behind the resilience score. Both are per-candidate sorts
        over the whole path matrix, and the counterfactual search discards every
        candidate but one.
        """
        as_of = as_of or date.today()
        buffer_paise = (
            safe_buffer if safe_buffer is not None else self.safe_buffer_paise(profile)
        )

        base_breach, _, _ = self._assess(
            self._run(profile, obligation, as_of, scenario=None), buffer_paise
        )
        if base_breach > self.breach_ceiling:
            return TwinVerdict.UNAFFORDABLE

        for shock in SHOCKS:
            if not self._shock_applies(shock, profile):
                continue
            breach, _, _ = self._assess(
                self._run(profile, obligation, as_of, scenario=shock.key), buffer_paise
            )
            if breach > self.breach_ceiling:
                return TwinVerdict.FRAGILE
        return TwinVerdict.AFFORDABLE

    def safe_buffer_paise(self, profile: CustomerProfile) -> int:
        """The customer's minimum safe buffer.

        Scaled by income type, which is the whole point of detecting it. A
        salaried customer needs roughly one month of committed outflow in
        reserve; a farmer between harvests needs three and a half. A single
        global floor would either strangle the salaried customer or leave the
        farmer exposed.
        """
        months = buffer_multiplier(profile.income_type)
        committed = profile.monthly_committed_outflow_paise + profile.existing_emi_paise
        by_obligation = int(months * committed)

        daily_total = (committed + profile.monthly_discretionary_paise) / DAYS_PER_MONTH
        by_days = int(settings.min_buffer_days * daily_total)

        # A floor of one week of income stops the buffer collapsing to zero for
        # customers with no detected committed outflow at all.
        by_income = int(profile.monthly_income_paise * 0.25)
        return max(by_obligation, by_days, by_income, 0)

    def counterfactual(
        self,
        profile: CustomerProfile,
        requested: Obligation,
        *,
        as_of: date | None = None,
        rate: float | None = None,
        tenure_options: tuple[int, ...] = (12, 18, 24, 30, 36, 48, 60),
        preferred_day: int | None = None,
    ) -> Counterfactual:
        """Find the structure at which the request becomes affordable.

        Searches tenure outward and binary-searches the principal within each,
        preferring the *shortest* tenure that works. That preference is not an
        optimisation detail: report §9.3 forbids presenting a longer tenure as a
        pure benefit, so the system must not reach for one when a shorter
        structure already clears.
        """
        from ..core.money import emi_paise

        as_of = as_of or date.today()
        annual_rate = rate if rate is not None else requested.annual_rate
        day = preferred_day or requested.day_of_month
        requested_principal = requested.principal_paise or _implied_principal(requested)
        safe_buffer = self.safe_buffer_paise(profile)

        best: Counterfactual | None = None

        for tenure in tenure_options:
            lo, hi = 0, requested_principal
            found = 0
            found_emi = 0
            for _ in range(12):                       # 12 bisections ≈ rupee-level precision
                mid = (lo + hi) // 2
                if mid <= 0:
                    break
                emi = emi_paise(mid, annual_rate, tenure) if annual_rate > 0 else mid // tenure
                trial = Obligation(
                    label=requested.label, emi_paise=emi, day_of_month=day,
                    tenure_months=tenure, principal_paise=mid, annual_rate=annual_rate,
                )
                verdict = self.verdict_for(
                    profile, trial, as_of=as_of, safe_buffer=safe_buffer
                )
                if verdict is TwinVerdict.AFFORDABLE:
                    found, found_emi = mid, emi
                    lo = mid
                else:
                    hi = mid
                if hi - lo <= max(1000 * 100, requested_principal // 200):
                    break

            if found > 0:
                candidate = Counterfactual(
                    available=True, amount_paise=found, tenure_months=tenure,
                    emi_paise=found_emi, day_of_month=day,
                    resilience_score=self.simulate(
                        profile,
                        Obligation(requested.label, found_emi, day, tenure, None, found, annual_rate),
                        as_of=as_of,
                    ).resilience_score,
                )
                # Take the first (shortest) tenure that carries a materially
                # useful amount; otherwise keep looking for more room.
                if best is None or candidate.amount_paise > best.amount_paise * 1.15:
                    best = candidate
                if candidate.amount_paise >= requested_principal * 0.6:
                    return candidate

        if best is not None:
            return best
        return Counterfactual(
            available=False,
            blocker=(
                "No amount at any offered tenure keeps the projected balance above the "
                "safe buffer. An emergency-fund plan is the correct recommendation."
            ),
        )

    def twin_safe_exposure_paise(
        self,
        profile: CustomerProfile,
        *,
        annual_rate: float,
        tenure_months: int,
        day_of_month: int,
        ceiling_paise: int,
        as_of: date | None = None,
    ) -> int:
        """The largest principal this customer's cash flow sustains.

        Report §5.2: limits and loan amounts are set here, not at maximum
        eligibility. ``ceiling_paise`` is the policy maximum; the return value is
        almost always below it, and that gap is the product.
        """
        probe = Obligation(
            label="exposure-probe",
            emi_paise=0, day_of_month=day_of_month,
            tenure_months=tenure_months, principal_paise=ceiling_paise,
            annual_rate=annual_rate,
        )
        cf = self.counterfactual(profile, probe, as_of=as_of, tenure_options=(tenure_months,))
        return cf.amount_paise if cf.available else 0

    # -- simulation core ----------------------------------------------------

    def _run(
        self,
        profile: CustomerProfile,
        obligation: Obligation | None,
        as_of: date,
        *,
        scenario: str | None,
    ) -> np.ndarray:
        """Return a [paths, horizon] matrix of end-of-day balances, in paise."""
        base = self._base_paths(profile, as_of, scenario)
        if obligation is None or obligation.emi_paise <= 0:
            return base
        return base - self._obligation_drawdown(obligation, as_of)

    def _base_paths(
        self, profile: CustomerProfile, as_of: date, scenario: str | None
    ) -> np.ndarray:
        """Balances with no candidate obligation, for one scenario.

        Cached, and returned read-only: every caller subtracts an obligation to
        make its own array, and a caller that mutated this one in place would
        silently corrupt every later trial in the same search.
        """
        key = (profile, as_of, scenario)
        hit = self._base_cache.get(key)
        if hit is not None:
            return hit

        T, P = self.horizon_days, self.paths
        # Seed is derived from customer and scenario so that scenarios are
        # independent but the whole result stays reproducible.
        rng = np.random.default_rng(
            stable_seed(self.seed, profile.customer_token, scenario or "base")
        )

        if scenario is not None and scenario.startswith(_STACK_PREFIX):
            paths = self._stacked_base(
                rng, profile, as_of, T, P, int(scenario[len(_STACK_PREFIX):])
            )
        else:
            inflow = self._income_matrix(rng, profile, as_of, T, P, scenario)
            outflow = self._outflow_matrix(rng, profile, as_of, T, P, scenario)
            paths = float(profile.balance_paise) + np.cumsum(inflow - outflow, axis=1)

        paths.flags.writeable = False
        if len(self._base_cache) >= self._base_cache_limit:
            self._base_cache.pop(next(iter(self._base_cache)))
        self._base_cache[key] = paths
        return paths

    def _obligation_drawdown(self, obligation: Obligation, as_of: date) -> np.ndarray:
        """Cumulative instalments paid by each day, as a [horizon] vector.

        One dimension rather than two: the repayment schedule is the same on
        every simulated path, so carrying a copy of it per path was only ever
        paying for the broadcast up front.
        """
        T = self.horizon_days
        out = np.zeros(T, dtype=float)
        first = obligation.first_due or _next_day_of_month(as_of, obligation.day_of_month)
        offset = (first - as_of).days
        month = 0
        while offset < T and month < obligation.tenure_months:
            if offset >= 0:
                out[int(offset)] += float(obligation.emi_paise)
            month += 1
            nxt = _add_months(first, month)
            offset = (nxt - as_of).days
        return np.cumsum(out)

    def _income_matrix(
        self, rng, profile: CustomerProfile, as_of: date, T: int, P: int, scenario: str | None
    ) -> np.ndarray:
        inc = np.zeros((P, T), dtype=float)
        streams = [
            s for s in profile.series
            if s.direction is Direction.CREDIT and s.category in {
                Category.SALARY, Category.GIG_PAYOUT, Category.AGRI_PROCEEDS,
                Category.BUSINESS_RECEIPTS, Category.GOVT_BENEFIT, Category.REMITTANCE_IN,
            }
        ]

        if not streams:
            # No detected series: spread assessed income evenly with wide
            # dispersion. Deliberately pessimistic — an income we cannot see the
            # shape of should not be modelled as if it were a salary.
            if profile.monthly_income_paise > 0:
                daily = profile.monthly_income_paise / DAYS_PER_MONTH
                inc += rng.gamma(1.5, daily / 1.5, size=(P, T))
            return inc

        day_sigma, amt_sigma = _dispersion(profile.income_type)
        delay = 15 if scenario == "income_delay" else 0

        for s in streams:
            occurrences = _occurrence_offsets(s, as_of, T)
            stream_sigma = max(amt_sigma, s.amount_volatility)
            for i, offset in enumerate(occurrences):
                jitter = rng.normal(0.0, day_sigma, P)
                idx = np.clip(np.round(offset + delay + jitter), 0, T - 1).astype(int)

                factor = rng.lognormal(mean=0.0, sigma=stream_sigma, size=P)
                factor = np.clip(factor, 0.35, 2.2)
                amounts = float(s.median_amount_paise) * factor

                if scenario == "missed_income" and i == 1:
                    # Lose the second cycle: far enough in that the customer has
                    # already committed to the EMI, close enough to be survivable
                    # if the structure is sound.
                    amounts = amounts * 0.0

                np.add.at(inc, (np.arange(P), idx), amounts)

        return inc

    def _outflow_matrix(
        self, rng, profile: CustomerProfile, as_of: date, T: int, P: int, scenario: str | None
    ) -> np.ndarray:
        out = np.zeros((P, T), dtype=float)

        # Committed obligations land on their day, with little dispersion.
        for s in profile.series:
            if s.direction is not Direction.DEBIT:
                continue
            if s.category not in {
                Category.RENT, Category.EMI, Category.INSURANCE_PREMIUM,
                Category.UTILITIES, Category.TELECOM, Category.SUBSCRIPTION,
                Category.EDUCATION,
            }:
                continue
            for offset in _occurrence_offsets(s, as_of, T):
                idx = np.clip(np.round(offset + rng.normal(0, 1.0, P)), 0, T - 1).astype(int)
                amounts = float(s.median_amount_paise) * np.clip(
                    rng.normal(1.0, max(0.05, s.amount_volatility), P), 0.6, 1.6
                )
                np.add.at(out, (np.arange(P), idx), amounts)

        # Discretionary spend as a daily draw. Gamma rather than normal: spending
        # is non-negative and right-skewed, and a normal draw produces negative
        # spend days that quietly inflate the projected balance.
        daily_disc = profile.monthly_discretionary_paise / DAYS_PER_MONTH
        if daily_disc > 0:
            out += rng.gamma(2.0, daily_disc / 2.0, size=(P, T))

        if scenario == "festival":
            start = min(int(45), T - 1)
            end = min(start + 12, T)
            out[:, start:end] *= 2.4

        if scenario == "medical":
            # A single unplanned expense at roughly one month of income, placed
            # in the middle of the horizon.
            shock_amount = max(profile.monthly_income_paise, 1500_00) * rng.uniform(0.8, 1.4, P)
            idx = np.clip(np.round(rng.normal(T * 0.5, 12, P)), 0, T - 1).astype(int)
            np.add.at(out, (np.arange(P), idx), shock_amount)

        return out

    # -- assessment ---------------------------------------------------------

    def _assess(self, balances: np.ndarray, safe_buffer: int) -> tuple[float, int | None, float]:
        below = balances < safe_buffer
        breached_any = below.any(axis=1)
        breach_probability = float(breached_any.mean())

        first_day: int | None = None
        if breached_any.any():
            first_indices = np.argmax(below[breached_any], axis=1)
            first_day = int(np.percentile(first_indices, 50))

        p05 = float(np.percentile(balances.min(axis=1), 5))
        return breach_probability, first_day, p05

    @staticmethod
    def _shock_applies(shock: Shock, profile: CustomerProfile) -> bool:
        if shock.key == "missed_income":
            # A missed cycle is the defining risk for gig, seasonal and business
            # income. For a stable salary it is a different event — job loss —
            # which the empathy calendar and Sentinel handle, not the Twin.
            return profile.income_type in {
                IncomeType.GIG, IncomeType.SEASONAL, IncomeType.AGRICULTURAL,
                IncomeType.BUSINESS, IncomeType.SALARIED_VOLATILE, IncomeType.UNKNOWN,
            }
        return True

    def _shocks_absorbed(
        self, profile: CustomerProfile, obligation: Obligation | None, as_of: date, safe_buffer: int
    ) -> int:
        """How many simultaneous income shocks the customer survives.

        This is what produces "you can absorb one delayed salary, but not two" —
        the sentence report §5.1 gives as the Twin's plain-language output. It is
        computed, not phrased.
        """
        absorbed = 0
        for n in (1, 2, 3):
            paths = self._run_stacked(profile, obligation, as_of, n)
            breach, _, _ = self._assess(paths, safe_buffer)
            if breach <= self.breach_ceiling:
                absorbed = n
            else:
                break
        return absorbed

    def _run_stacked(
        self, profile: CustomerProfile, obligation: Obligation | None, as_of: date, n_shocks: int
    ) -> np.ndarray:
        return self._run(profile, obligation, as_of, scenario=f"{_STACK_PREFIX}{n_shocks}")

    def _stacked_base(
        self, rng, profile: CustomerProfile, as_of: date, T: int, P: int, n_shocks: int
    ) -> np.ndarray:
        inflow = self._income_matrix(rng, profile, as_of, T, P, scenario=None)

        # Remove the first n income events outright: the cleanest way to express
        # "n shocks" without compounding unrelated scenario machinery.
        cumulative = np.cumsum(inflow > 0, axis=1)
        inflow = np.where(cumulative <= n_shocks, 0.0, inflow)

        outflow = self._outflow_matrix(rng, profile, as_of, T, P, scenario=None)
        return float(profile.balance_paise) + np.cumsum(inflow - outflow, axis=1)

    @staticmethod
    def _resilience(base_breach: float, scenarios: list[ScenarioResult], absorbed: int) -> float:
        """0–100. Half the weight on the base case, half on shock survival."""
        base_component = (1.0 - min(base_breach * 4.0, 1.0)) * 50.0
        if scenarios:
            passed = sum(1 for s in scenarios if s.passed) / len(scenarios)
        else:
            passed = 1.0
        shock_component = passed * 35.0
        depth_component = min(absorbed, 3) / 3.0 * 15.0
        return round(float(np.clip(base_component + shock_component + depth_component, 0, 100)), 1)

    @staticmethod
    def _sentence(
        verdict: TwinVerdict,
        absorbed: int,
        scenarios: list[ScenarioResult],
        first_breach_day: int | None,
        as_of: date,
    ) -> tuple[str, dict[str, str]]:
        """Which sentence applies, and what fills it in.

        Returns the case rather than the prose so the same verdict can be spoken
        in any of the supported languages without this method — the one place
        that decides *what* is true — needing to know which one.
        """
        if verdict is TwinVerdict.UNAFFORDABLE and first_breach_day is not None:
            breach = as_of + timedelta(days=first_breach_day)
            return "breach", {"month_index": str(breach.month)}
        if verdict is TwinVerdict.FRAGILE:
            failed = next((s for s in scenarios if not s.passed), None)
            return "fragile", {"shock": failed.key if failed else "unexpected"}
        if absorbed >= 2:
            return "absorbs_two", {}
        if absorbed == 1:
            return "absorbs_one", {}
        return "no_room", {}


# --- helpers ----------------------------------------------------------------


def _dispersion(income_type: IncomeType) -> tuple[float, float]:
    """(day jitter sigma, amount log-sigma) by income profile."""
    return {
        IncomeType.SALARIED_STABLE: (1.2, 0.06),
        IncomeType.SALARIED_VOLATILE: (3.5, 0.18),
        IncomeType.GIG: (5.0, 0.35),
        IncomeType.BUSINESS: (6.0, 0.40),
        IncomeType.SEASONAL: (8.0, 0.45),
        IncomeType.AGRICULTURAL: (10.0, 0.50),
        IncomeType.UNKNOWN: (6.0, 0.35),
    }[income_type]


def _occurrence_offsets(series: RecurringSeries, as_of: date, horizon: int) -> list[int]:
    """Day offsets from ``as_of`` at which this series is expected to recur."""
    offsets: list[int] = []
    if series.period_days >= 28 and series.day_of_month:
        cursor = _next_day_of_month(as_of, series.day_of_month)
        step = 0
        while (cursor - as_of).days < horizon:
            offsets.append((cursor - as_of).days)
            step += 1
            cursor = _add_months(_next_day_of_month(as_of, series.day_of_month), step)
    else:
        offset = series.period_days - ((as_of - series.last_seen).days % max(series.period_days, 1))
        while offset < horizon:
            offsets.append(int(offset))
            offset += series.period_days
    return [o for o in offsets if 0 <= o < horizon]


def _next_day_of_month(d: date, day: int) -> date:
    day = max(1, min(day, 28))
    if d.day < day:
        return date(d.year, d.month, day)
    return _add_months(date(d.year, d.month, day), 1)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _implied_principal(obligation: Obligation) -> int:
    if obligation.principal_paise:
        return obligation.principal_paise
    return obligation.emi_paise * max(obligation.tenure_months, 1)


def path_day_offsets(horizon_days: int) -> tuple[int, ...]:
    """The day each down-sampled chart point actually stands for.

    Sent alongside the paths because the chart cannot infer it. Sampling every
    ``step`` days and then spreading the points evenly across the horizon is
    off by up to a whole step at the right-hand end: with a 180-day horizon the
    final point is day 174 and the axis labelled it 180, so every reading the
    customer took off the chart was wrong by up to a week — and the customer is
    consenting to this picture.
    """
    return tuple(_sample_indices(horizon_days))


def _sample_indices(length: int) -> list[int]:
    step = max(1, length // 26)
    idx = list(range(0, length, step))
    # Always carry the last day. Without it the series stops short of the
    # horizon it claims to cover, which is the difference between a projection
    # to six months and a projection to five and a half.
    if idx[-1] != length - 1:
        idx.append(length - 1)
    return idx


def _quantile_path(balances: np.ndarray, q: float) -> tuple[int, ...]:
    """Down-sample a path to roughly weekly points for transport to the UI.

    180 daily points per series is more than any chart renders usefully and more
    than a feature-phone session should carry.
    """
    path = np.percentile(balances, q * 100, axis=0)
    return tuple(int(path[i]) for i in _sample_indices(len(path)))


def describe(result: TwinResult, lang: str = "en") -> dict[str, str]:
    """Human-readable summary used by the consent screen and the banker console."""
    return {
        "verdict": result.verdict.value,
        "sentence": result.sentence_en,
        "safe_buffer": format_inr(result.safe_buffer_paise),
        "safe_buffer_spoken": spoken_inr(result.safe_buffer_paise, lang).phrase,
        "lowest_projected": format_inr(result.min_balance_p05_paise),
        "resilience_score": f"{result.resilience_score:.0f}/100",
        "shocks_absorbed": str(result.shocks_absorbed),
    }
