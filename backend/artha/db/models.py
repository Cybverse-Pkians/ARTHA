"""Operational persistence.

Report §8, Datastore row: "PostgreSQL for operational data; append-only store for
the audit log — decision persistence and immutable regulatory audit trail."

Two tables carry the regulatory weight and are shaped accordingly.

``decisions`` stores the **regulator rendering verbatim** rather than a set of
extracted columns. A supervisor asking why a customer was refused in March needs
the trace as it was, not a reconstruction from whichever fields seemed worth
indexing at the time. The indexed columns beside it exist for querying, not for
truth.

``audit_records`` is append-only and hash-chained. There is no ORM update path
for it: the class exposes no mutable interface, and in deployment the table is
additionally protected at the database level (revoke UPDATE and DELETE from the
application role, and prefer an append-only store where one is available). A
hash chain detects tampering; it does not prevent it, and the two controls are
complementary rather than alternatives.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Customer(Base):
    """Tokenised customer reference.

    No name, no PAN, no account number, no contact details. Personal identifiers
    are tokenised on entry (report §4.1) and resolved only through the vault,
    which logs every reversal with a stated reason.
    """

    __tablename__ = "customers"

    customer_token: Mapped[str] = mapped_column(String(64), primary_key=True)
    language: Mapped[str] = mapped_column(String(8), default="hi")
    district: Mapped[str] = mapped_column(String(64), default="")
    is_rural: Mapped[bool] = mapped_column(Boolean, default=False)
    income_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    income_type_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_state: Mapped[str] = mapped_column(String(16), default="STABLE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    decisions: Mapped[list["Decision"]] = relationship(back_populates="customer")


class Decision(Base):
    __tablename__ = "decisions"

    decision_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_token: Mapped[str] = mapped_column(
        String(64), ForeignKey("customers.customer_token"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    outcome: Mapped[str] = mapped_column(String(16), index=True)
    blocking_check: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    product_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    eligible_amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    emi_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    twin_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resilience_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_adverse_action: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    policy_version: Mapped[str] = mapped_column(String(16))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)

    # The regulator rendering, verbatim. The source of truth; everything above
    # is an index into it.
    regulator_rendering: Mapped[dict] = mapped_column(JSON)

    customer: Mapped["Customer"] = relationship(back_populates="decisions")

    __table_args__ = (
        Index("ix_decisions_customer_created", "customer_token", "created_at"),
        Index("ix_decisions_outcome_created", "outcome", "created_at"),
    )


class AuditRecordRow(Base):
    """Append-only, hash-chained. Never updated, never deleted."""

    __tablename__ = "audit_records"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    record_type: Mapped[str] = mapped_column(String(32), index=True)
    customer_token: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    payload: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)

    __table_args__ = (
        Index("ix_audit_customer_type", "customer_token", "record_type"),
    )


class ConsentGrantRow(Base):
    __tablename__ = "consent_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_token: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str] = mapped_column(String(48), index=True)
    granted_at: Mapped[Date] = mapped_column(Date)
    expires_at: Mapped[Date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(32), default="app")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_consent_customer_purpose", "customer_token", "purpose"),
    )


class ContactRow(Base):
    """Feeds the nudge budget and the per-product cooldown."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_token: Mapped[str] = mapped_column(String(64), index=True)
    product_family: Mapped[str] = mapped_column(String(32), index=True)
    contacted_on: Mapped[Date] = mapped_column(Date, index=True)
    channel: Mapped[str] = mapped_column(String(16), default="APP")
    decision_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RecoveryEventRow(Base):
    __tablename__ = "recovery_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_token: Mapped[str] = mapped_column(String(64), index=True)
    at: Mapped[Date] = mapped_column(Date, index=True)
    from_state: Mapped[str] = mapped_column(String(16))
    to_state: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(64), default="system")


class SuppressionRow(Base):
    """Offers the Gate declined to make.

    Stored because report §2.2 reports suppressions as a success metric, and
    §8.1 feeds them back as catalogue optimisation — which product terms most
    often cause a suitability rejection.
    """

    __tablename__ = "suppressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_token: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[str] = mapped_column(String(48), index=True)
    blocking_check: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
