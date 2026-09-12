"""Enrichment pipeline: raw transactions in, typed financial behaviour out.

This is the only place in ARTHA where a narration string is read. Everything
downstream consumes :class:`EnrichedTransaction` and :class:`RecurringSeries`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..core.types import (
    COMMITTED_OUTFLOW_CATEGORIES,
    DISCRETIONARY_CATEGORIES,
    INCOME_CATEGORIES,
    Category,
    Direction,
    EnrichedTransaction,
    IncomeType,
    RecurringSeries,
    Transaction,
)
from . import income_type as income_typing
from . import recurrence
from .merchants import DEFAULT_RESOLVER, MerchantResolver
from .narration import DEFAULT_PARSER, InjectionFinding, NarrationParser


@dataclass(frozen=True)
class EnrichmentResult:
    enriched: list[EnrichedTransaction]
    series: list[RecurringSeries]
    income: income_typing.IncomeTypeResult
    injection_findings: list[tuple[str, InjectionFinding]] = field(default_factory=list)
    unclassified_share: float = 0.0

    @property
    def monthly_income_paise(self) -> int:
        return _monthly_income(self.series, self.enriched)

    @property
    def monthly_committed_outflow_paise(self) -> int:
        return sum(
            _to_monthly(s.median_amount_paise, s.period_days)
            for s in recurrence.obligation_series(self.series)
        )

    @property
    def existing_emi_paise(self) -> int:
        return sum(
            _to_monthly(s.median_amount_paise, s.period_days)
            for s in self.series
            if s.direction is Direction.DEBIT and s.category is Category.EMI
        )


class EnrichmentPipeline:
    def __init__(
        self,
        parser: NarrationParser | None = None,
        resolver: MerchantResolver | None = None,
    ) -> None:
        self.parser = parser or DEFAULT_PARSER
        self.resolver = resolver or DEFAULT_RESOLVER

    def run(
        self,
        transactions: list[Transaction],
        *,
        income_override: IncomeType | None = None,
        income_model: object | None = None,
        as_of: date | None = None,
    ) -> EnrichmentResult:
        enriched: list[EnrichedTransaction] = []
        findings: list[tuple[str, InjectionFinding]] = []
        unclassified = 0

        for txn in transactions:
            parsed = self.parser.parse(txn)
            for finding in parsed.injection_findings:
                findings.append((txn.txn_id, finding))
            if parsed.parser == "fallback":
                unclassified += 1

            enriched.append(
                EnrichedTransaction(
                    txn=txn,
                    category=parsed.category,
                    merchant=self.resolver.get(parsed.merchant_id) if parsed.merchant_id else None,
                    counterparty_key=parsed.counterparty_key,
                    confidence=parsed.confidence,
                    parser=parsed.parser,
                )
            )

        series = recurrence.detect_series(enriched, as_of=as_of)

        # Mark membership so a single transaction can be shown as part of a series
        # in the banker console's evidence view.
        series_by_key = {s.series_id: s for s in series}
        enriched = [_attach_series(e, series_by_key) for e in enriched]

        income = income_typing.classify(
            enriched, series, override=income_override, model=income_model, as_of=as_of
        )

        return EnrichmentResult(
            enriched=enriched,
            series=series,
            income=income,
            injection_findings=findings,
            unclassified_share=round(unclassified / max(len(transactions), 1), 4),
        )


def _attach_series(
    e: EnrichedTransaction, series_by_key: dict[str, RecurringSeries]
) -> EnrichedTransaction:
    key = e.counterparty_key or (e.merchant.merchant_id if e.merchant else None)
    if key is None and e.category in COMMITTED_OUTFLOW_CATEGORIES:
        key = f"c:{e.category.value}"
    if key is None:
        return e
    sid = f"{key}|{e.category.value}|{e.direction.value}"
    if sid in series_by_key:
        return EnrichedTransaction(
            txn=e.txn, category=e.category, merchant=e.merchant,
            counterparty_key=e.counterparty_key, is_recurring=True,
            series_id=sid, confidence=e.confidence, parser=e.parser,
        )
    return e


def _to_monthly(amount_paise: int, period_days: int) -> int:
    """Normalise any period to a monthly equivalent."""
    if period_days <= 0:
        return 0
    return int(round(amount_paise * (30.44 / period_days)))


def _monthly_income(series: list[RecurringSeries], enriched: list[EnrichedTransaction]) -> int:
    """Assessed monthly income: total income observed, divided by the window.

    It is tempting to annualise the detected recurring series instead, since
    those are the reliable part of income. That is a trap for exactly the
    customers this system exists for. A farmer's October, November and December
    proceeds sit thirty days apart, so the recurrence detector legitimately
    calls them a monthly series — and multiplying a harvest payment by twelve
    invents an income the customer does not have, which the Twin then clears
    loans against.

    The observed average is the honest estimate for every profile, and where it
    is wrong it is wrong conservatively. The series are still used, but for what
    they actually establish: *timing* and reliability, which is what the Twin and
    the Profitability Engine consume them for.
    """
    credits = [
        e for e in enriched
        if e.direction is Direction.CREDIT and e.category in INCOME_CATEGORIES
    ]
    if not credits:
        return 0
    dates = [e.value_date for e in credits]
    months = max((max(dates) - min(dates)).days / 30.44, 1.0)
    return int(round(sum(abs(e.amount_paise) for e in credits) / months))


def monthly_discretionary_paise(enriched: list[EnrichedTransaction]) -> int:
    spend = [e for e in enriched if e.direction is Direction.DEBIT
             and e.category in DISCRETIONARY_CATEGORIES]
    if not spend:
        return 0
    dates = [e.value_date for e in spend]
    months = max((max(dates) - min(dates)).days / 30.44, 1.0)
    return int(round(sum(abs(e.amount_paise) for e in spend) / months))


DEFAULT_PIPELINE = EnrichmentPipeline()
