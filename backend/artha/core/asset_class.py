"""Supervisory asset classification — the ladder ARTHA does *not* own.

Report §6.5 describes a behavioural state machine (`gate/recovery.py`). This
module is the other ladder: the one the regulator defines, the bank must report,
and ARTHA can only observe. Until this existed, the system had a behavioural
state and no regulatory state, and the claim that ARTHA acts *before* the
supervisory ladder notices could not be evaluated — there was nothing to compare
against.

The two ladders answer different questions:

* ``RecoveryState`` — *what do we think is happening, and what should we do?*
  Forward-looking, inferred from behaviour, customer-level, ours to choose.
* ``SmaState`` — *what is this account, for reporting and provisioning?*
  Backward-looking, mechanical from days past due, account-level, prescribed.

The distance between them is the product. A customer can be ``AT_RISK`` while
every account is still ``STANDARD``; that window — behaviour already broken,
the supervisory ladder not yet moved — is where an intervention is cheap. Once
an account leaves STANDARD the bank's collections and fair-practices policy owns
the relationship, and ARTHA's role narrows to informing a human.

REGULATORY STATUS — a design hypothesis, consistent with `docs/CLAIMS_REGISTER.md`
§1. The day bands below are the widely documented Special Mention Account
buckets, but they are reproduced here from secondary understanding and MUST be
verified against the current RBI circulars (the Prudential Framework for
Resolution of Stressed Assets and the subsequent IRACP clarifications) before
submission or presentation. `VERIFY_AGAINST_CIRCULAR` is exported so callers can
surface that caveat rather than bury it, and the API does surface it.

Deliberately NOT modelled, because modelling them badly would be worse than
omitting them: provisioning percentages, CRILC reporting (which applies at an
aggregate-exposure threshold retail loans do not reach), NPA sub-classification
into doubtful and loss, and the upgrade rules for an account that has already
become an NPA.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

VERIFY_AGAINST_CIRCULAR = (
    "Special Mention Account day bands are stated here as a design hypothesis "
    "and must be verified against the current RBI circulars before being relied "
    "upon. See docs/CLAIMS_REGISTER.md §1."
)

#: Upper bound of each band, in days past due. The band a DPD falls into is the
#: first whose bound it does not exceed; beyond the last bound the account is an
#: NPA. Kept as data rather than branches so the boundaries can be read, tested
#: and corrected in one place when the circular is checked.
_BANDS: tuple[tuple[int, "SmaState"], ...] = ()  # populated below


class SmaState(str, Enum):
    """Supervisory classification of a *loan account* by days past due.

    Ordered. ``STANDARD`` is healthy; ``NPA`` is the outcome every rung of the
    Intervention Ladder exists to avoid.
    """

    STANDARD = "STANDARD"   # nothing overdue
    SMA_0 = "SMA_0"         # 1-30 days past due
    SMA_1 = "SMA_1"         # 31-60 days past due
    SMA_2 = "SMA_2"         # 61-90 days past due
    NPA = "NPA"             # more than 90 days past due

    @property
    def rank(self) -> int:
        return _RANK[self]

    @property
    def is_stressed(self) -> bool:
        """Anything the supervisor would not call Standard."""
        return self is not SmaState.STANDARD

    @property
    def is_npa(self) -> bool:
        return self is SmaState.NPA

    @property
    def band_label(self) -> str:
        return _BAND_LABELS[self]

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SmaState):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SmaState):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SmaState):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SmaState):
            return NotImplemented
        return self.rank >= other.rank


_RANK: dict[SmaState, int] = {
    SmaState.STANDARD: 0,
    SmaState.SMA_0: 1,
    SmaState.SMA_1: 2,
    SmaState.SMA_2: 3,
    SmaState.NPA: 4,
}

_BAND_LABELS: dict[SmaState, str] = {
    SmaState.STANDARD: "not overdue",
    SmaState.SMA_0: "1-30 days past due",
    SmaState.SMA_1: "31-60 days past due",
    SmaState.SMA_2: "61-90 days past due",
    SmaState.NPA: "more than 90 days past due",
}

_BANDS = (
    (0, SmaState.STANDARD),
    (30, SmaState.SMA_0),
    (60, SmaState.SMA_1),
    (90, SmaState.SMA_2),
)

#: Days past due at which an account becomes an NPA.
NPA_THRESHOLD_DAYS = 90


def classify(days_past_due: int) -> SmaState:
    """Classify a term-loan account from its days past due.

    Classification is a day-end position: a payment due today and unpaid is 0
    days past due and the account is still Standard. A negative value — a
    payment made ahead of its due date — is treated as Standard rather than
    rejected, because a caller computing ``as_of - due_date`` will legitimately
    produce one.
    """
    if days_past_due < 0:
        return SmaState.STANDARD
    for bound, state in _BANDS:
        if days_past_due <= bound:
            return state
    return SmaState.NPA


def classify_revolving(days_continuously_in_excess: int) -> SmaState:
    """Classify a revolving facility (cash credit / overdraft).

    The measure is different in kind: not days past due but days the outstanding
    has stood *continuously* in excess of the sanctioned limit or drawing power.
    The commonly documented framework defines SMA-1 and SMA-2 for revolving
    facilities on the same 31-60 and 61-90 day windows, and does **not** define
    an SMA-0 equivalent — so this function never returns ``SMA_0``. Collapsing
    the two measures into one function would have quietly invented a category.
    """
    if days_continuously_in_excess <= 30:
        return SmaState.STANDARD
    if days_continuously_in_excess <= 60:
        return SmaState.SMA_1
    if days_continuously_in_excess <= NPA_THRESHOLD_DAYS:
        return SmaState.SMA_2
    return SmaState.NPA


def days_until(days_past_due: int, target: SmaState) -> int | None:
    """Days remaining before an account at ``days_past_due`` reaches ``target``.

    ``None`` when the account is already at or past that classification. This is
    the arithmetic behind the counterfactual the demo turns on — "on the current
    trajectory this account is SMA-1 in 41 days" — and it is stated as a
    trajectory, never as a prediction that it will happen.
    """
    current = classify(days_past_due)
    if current >= target:
        return None
    entry = _ENTRY_DPD.get(target)
    if entry is None:
        return None
    return max(entry - max(days_past_due, 0), 0)


#: The first DPD value that lands in each band.
_ENTRY_DPD: dict[SmaState, int] = {
    SmaState.SMA_0: 1,
    SmaState.SMA_1: 31,
    SmaState.SMA_2: 61,
    SmaState.NPA: NPA_THRESHOLD_DAYS + 1,
}


@dataclass(frozen=True)
class AssetClassification:
    """One account's supervisory position, with the caveat attached.

    Carries the caveat as data rather than leaving it to a docstring nobody
    renders — every surface that shows a classification shows why it is
    provisional.
    """

    days_past_due: int
    state: SmaState
    band_label: str
    days_to_next_downgrade: int | None
    next_state: SmaState | None
    verify_against_circular: str = VERIFY_AGAINST_CIRCULAR

    @classmethod
    def of(cls, days_past_due: int) -> "AssetClassification":
        state = classify(days_past_due)
        nxt = _NEXT.get(state)
        return cls(
            days_past_due=max(days_past_due, 0),
            state=state,
            band_label=state.band_label,
            days_to_next_downgrade=days_until(days_past_due, nxt) if nxt else None,
            next_state=nxt,
        )

    def render(self) -> dict:
        return {
            "days_past_due": self.days_past_due,
            "state": self.state.value,
            "band": self.band_label,
            "is_stressed": self.state.is_stressed,
            "next_state": self.next_state.value if self.next_state else None,
            "days_to_next_downgrade": self.days_to_next_downgrade,
            "verify_against_circular": self.verify_against_circular,
        }


_NEXT: dict[SmaState, SmaState | None] = {
    SmaState.STANDARD: SmaState.SMA_0,
    SmaState.SMA_0: SmaState.SMA_1,
    SmaState.SMA_1: SmaState.SMA_2,
    SmaState.SMA_2: SmaState.NPA,
    SmaState.NPA: None,
}


# --- the bridge -------------------------------------------------------------

#: Where each behavioural state sits on a 0-3 scale of concern, so it can be
#: compared against a supervisory rank. This mapping is a *design choice*, not a
#: regulatory one, and is the single place the two ladders are aligned.
_BEHAVIOURAL_CONCERN: dict[str, int] = {
    "STABLE": 0,
    "WATCH": 1,
    "AT_RISK": 2,
    "RECOVERY": 3,
}


@dataclass(frozen=True)
class SupervisoryGap:
    """How far ahead of the supervisory ladder the behavioural one is running.

    This is the measurable form of the system's central claim. ARTHA asserts
    that it acts while an account is still Standard; that assertion is only
    checkable if both positions are computed and compared, which is what this
    type exists to do.

    ``lead`` is positive when behaviour has moved and the supervisory ladder has
    not — the window in which an intervention is still cheap. It is zero or
    negative when the supervisory ladder has caught up or moved first, and a
    negative value is worth surfacing rather than hiding: it means the account
    went overdue without the behavioural machinery having flagged anything, and
    that is a miss.
    """

    recovery_state: str
    asset: AssetClassification

    @property
    def behavioural_concern(self) -> int:
        return _BEHAVIOURAL_CONCERN.get(self.recovery_state, 0)

    @property
    def lead(self) -> int:
        return self.behavioural_concern - self.asset.state.rank

    @property
    def acting_early(self) -> bool:
        """Behaviour has moved while every account is still Standard."""
        return self.behavioural_concern > 0 and not self.asset.state.is_stressed

    @property
    def missed(self) -> bool:
        """The account is overdue and the behavioural machinery never moved."""
        return self.asset.state.is_stressed and self.behavioural_concern == 0

    def render(self) -> dict:
        return {
            "recovery_state": self.recovery_state,
            "asset_classification": self.asset.render(),
            "behavioural_concern": self.behavioural_concern,
            "lead": self.lead,
            "acting_early": self.acting_early,
            "missed": self.missed,
            "note": (
                "Behavioural state is ARTHA's own and forward-looking; asset "
                "classification is prescribed and backward-looking. A positive "
                "lead is the window this system exists to act in."
            ),
        }
