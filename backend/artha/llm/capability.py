"""Capability tokens.

Report §7.7, third bullet: the model cannot call an approval or transfer
function. It emits a *proposed* action; the policy engine mints a signed,
single-use, scoped token; execution additionally requires explicit customer
confirmation.

The sequence is propose → preview → confirm → execute, with the model present
only at the first step. This module owns the last three.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum

from ..config import settings


class Capability(str, Enum):
    """Actions that may be taken on a customer's behalf.

    Deliberately short. Anything not on this list cannot be minted, and
    therefore cannot be executed, regardless of what any component proposes.
    """

    PRESENT_OFFER = "PRESENT_OFFER"
    ACCEPT_OFFER = "ACCEPT_OFFER"
    SHIFT_EMI_DATE = "SHIFT_EMI_DATE"
    ENTER_RECOVERY_MODE = "ENTER_RECOVERY_MODE"
    PLACE_FRAUD_HOLD = "PLACE_FRAUD_HOLD"
    BOOK_HUMAN_CALLBACK = "BOOK_HUMAN_CALLBACK"
    REVOKE_CONSENT_PURPOSE = "REVOKE_CONSENT_PURPOSE"


@dataclass(frozen=True)
class CapabilityToken:
    token_id: str
    capability: Capability
    decision_id: str
    customer_token: str
    issued_at: float
    expires_at: float
    signature: str
    requires_customer_confirmation: bool = True

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    def payload(self) -> dict:
        return {
            "token_id": self.token_id,
            "capability": self.capability.value,
            "decision_id": self.decision_id,
            "customer_token": self.customer_token,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


class TokenRejected(Exception):
    pass


class CapabilityBroker:
    """Mints and redeems capability tokens.

    Single-use is enforced by a redeemed-nonce set. In deployment that set is a
    shared store with a TTL; the in-process version here is correct for one
    node and is the one place this module would need changing to run behind a
    load balancer, which is worth stating plainly rather than discovering.
    """

    def __init__(self, secret: str | None = None, ttl_seconds: int | None = None) -> None:
        self._secret = (secret or settings.vault_secret).encode()
        self._ttl = ttl_seconds or settings.capability_token_ttl_seconds
        self._redeemed: set[str] = set()

    def mint(
        self,
        capability: Capability,
        *,
        decision_id: str,
        customer_token: str,
        requires_customer_confirmation: bool = True,
    ) -> CapabilityToken:
        now = time.time()
        # Coerce so a caller passing the bare string still yields a token whose
        # `capability` is the enum; the scope check downstream compares enum
        # members and would silently never match a string.
        capability = Capability(capability)

        unsigned = CapabilityToken(
            token_id=f"cap_{uuid.uuid4().hex}",
            capability=capability,
            decision_id=decision_id,
            customer_token=customer_token,
            issued_at=now,
            expires_at=now + self._ttl,
            signature="",
            requires_customer_confirmation=requires_customer_confirmation,
        )
        return replace(unsigned, signature=self._sign(unsigned.payload()))

    def redeem(
        self,
        token: CapabilityToken,
        *,
        customer_confirmed: bool,
        expected_capability: Capability | None = None,
    ) -> None:
        """Consume a token, or raise. Every rejection path is explicit.

        Customer confirmation is checked here rather than by the caller, so
        there is no route to execution that bypasses it by forgetting to ask.
        """
        if not hmac.compare_digest(token.signature, self._sign(token.payload())):
            raise TokenRejected("signature mismatch")
        if token.expired:
            raise TokenRejected("token expired")
        if token.token_id in self._redeemed:
            raise TokenRejected("token already redeemed")
        if expected_capability and token.capability is not expected_capability:
            raise TokenRejected(
                f"capability mismatch: token grants {token.capability.value}, "
                f"call requires {expected_capability.value}"
            )
        if token.requires_customer_confirmation and not customer_confirmed:
            raise TokenRejected("explicit customer confirmation not recorded")
        self._redeemed.add(token.token_id)

    def _sign(self, body: dict) -> str:
        blob = json.dumps(body, sort_keys=True).encode()
        return hmac.new(self._secret, blob, hashlib.sha256).hexdigest()


DEFAULT_BROKER = CapabilityBroker()
