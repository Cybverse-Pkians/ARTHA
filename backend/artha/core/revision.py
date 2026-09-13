"""Per-customer mutation counters.

The orchestrator caches decisions, because a surface asking the same question
twice means "tell me again", not "decide again" — deciding consumes the
customer's nudge budget and writes to the audit log. A cache over something with
side effects is only safe if it can tell staleness from reuse, and the honest way
to do that is for the mutable components to say when they changed rather than for
callers to remember to announce it.

Counters are per customer so that one customer's decision cannot invalidate
another's. A global counter would make a console screen that decides eleven
customers in a row invalidate the first ten while computing the eleventh, which
is the thrashing the cache exists to remove.
"""

from __future__ import annotations


class RevisionCounter:
    """Counts mutations, by customer token."""

    __slots__ = ("_revisions",)

    def __init__(self) -> None:
        self._revisions: dict[str, int] = {}

    def bump(self, customer_token: str) -> None:
        self._revisions[customer_token] = self._revisions.get(customer_token, 0) + 1

    def of(self, customer_token: str) -> int:
        return self._revisions.get(customer_token, 0)
