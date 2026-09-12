"""Append-only audit log and evidence-pack export.

Report §6.7 and §9.4. Two requirements this serves:

* an immutable audit trail, exportable as an evidence pack;
* the structural defence against an evergreening reading — **detection is
  separated from forbearance**. The Sentinel reports stress to the bank's risk
  function unconditionally, whether or not an intervention follows, and the
  decision to assist is a separate, logged step.

That separation is enforced here by having two distinct record types that are
written independently. A stress observation is written when it is observed. An
intervention record is written when an intervention is offered. Nothing in the
API allows the first to be suppressed because the second happened, so the log
cannot show assistance without also showing the stress that prompted it.

Entries are hash-chained: each record carries the digest of the one before it,
so a deleted or altered record breaks the chain verifiably.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class RecordType(str, Enum):
    DECISION = "DECISION"
    STRESS_OBSERVATION = "STRESS_OBSERVATION"
    INTERVENTION_OFFERED = "INTERVENTION_OFFERED"
    INTERVENTION_ACCEPTED = "INTERVENTION_ACCEPTED"
    INTERVENTION_DECLINED = "INTERVENTION_DECLINED"
    RECOVERY_TRANSITION = "RECOVERY_TRANSITION"
    FRAUD_HOLD = "FRAUD_HOLD"
    CONSENT_CHANGE = "CONSENT_CHANGE"
    HUMAN_OVERRIDE = "HUMAN_OVERRIDE"
    INJECTION_DETECTED = "INJECTION_DETECTED"
    FIREWALL_BLOCK = "FIREWALL_BLOCK"


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    record_type: RecordType
    customer_token: str
    at: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str
    actor: str = "system"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["record_type"] = self.record_type.value
        return d


class AuditLog:
    """In-memory append-only log with a verifiable hash chain.

    A deployment writes these records to an append-only store (report §8,
    Datastore row). The chain logic is identical either way; only the sink
    changes, and keeping it here means the integrity property is testable
    without a database.
    """

    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(
        self,
        record_type: RecordType,
        customer_token: str,
        payload: dict,
        *,
        actor: str = "system",
    ) -> AuditRecord:
        prev = self._records[-1].hash if self._records else self.GENESIS
        seq = len(self._records)
        at = datetime.now(UTC).isoformat(timespec="seconds")
        body = {
            "seq": seq,
            "record_type": record_type.value,
            "customer_token": customer_token,
            "at": at,
            "payload": payload,
            "prev_hash": prev,
            "actor": actor,
        }
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()
        record = AuditRecord(
            seq=seq, record_type=record_type, customer_token=customer_token,
            at=at, payload=payload, prev_hash=prev, hash=digest, actor=actor,
        )
        self._records.append(record)
        return record

    def verify(self) -> tuple[bool, str]:
        """Re-walk the chain. Returns (ok, detail)."""
        prev = self.GENESIS
        for record in self._records:
            if record.prev_hash != prev:
                return False, f"chain broken at seq {record.seq}"
            body = {
                "seq": record.seq,
                "record_type": record.record_type.value,
                "customer_token": record.customer_token,
                "at": record.at,
                "payload": record.payload,
                "prev_hash": record.prev_hash,
                "actor": record.actor,
            }
            expected = hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode()
            ).hexdigest()
            if expected != record.hash:
                return False, f"record {record.seq} has been altered"
            prev = record.hash
        return True, f"{len(self._records)} records verified"

    def for_customer(self, customer_token: str) -> list[AuditRecord]:
        return [r for r in self._records if r.customer_token == customer_token]

    def of_type(self, record_type: RecordType) -> list[AuditRecord]:
        return [r for r in self._records if r.record_type is record_type]

    def evidence_pack(self, customer_token: str) -> dict:
        """Everything a supervisor would ask for about one customer.

        Deliberately includes the stress observations *and* the interventions as
        separate sections, because the question being answered is not only "what
        did you do" but "what did you know, and when".
        """
        records = self.for_customer(customer_token)
        ok, detail = self.verify()
        return {
            "customer_token": customer_token,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "chain_integrity": {"verified": ok, "detail": detail},
            "record_count": len(records),
            "stress_observations": [
                r.to_dict() for r in records if r.record_type is RecordType.STRESS_OBSERVATION
            ],
            "interventions": [
                r.to_dict() for r in records
                if r.record_type in {
                    RecordType.INTERVENTION_OFFERED,
                    RecordType.INTERVENTION_ACCEPTED,
                    RecordType.INTERVENTION_DECLINED,
                }
            ],
            "decisions": [
                r.to_dict() for r in records if r.record_type is RecordType.DECISION
            ],
            "all_records": [r.to_dict() for r in records],
        }

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)


DEFAULT_LOG = AuditLog()
