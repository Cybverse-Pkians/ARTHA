"""Tokenisation vault.

Report §4.1: personal identifiers are tokenised in a vault on entry, and all
processing takes place inside the bank's own environment. Everything downstream
of ingestion handles tokens, which is what allows report §7.7 to claim that full
compromise of the language model leaks nothing identifying.

The implementation here is a keyed-hash tokeniser with an in-memory reverse map.
That is the correct *shape* — deterministic tokens, detokenisation only through
an explicit call that can be logged and access-controlled — but a deployment
backs it with an HSM or a managed key service rather than a process dictionary,
and that substitution is the only change required.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

from ..config import settings


@dataclass
class TokenisationVault:
    secret: str = field(default_factory=lambda: settings.vault_secret)
    _reverse: dict[str, str] = field(default_factory=dict, repr=False)
    _access_log: list[tuple[str, str]] = field(default_factory=list, repr=False)

    def tokenise(self, value: str, *, kind: str = "pan") -> str:
        if not value:
            return ""
        digest = hmac.new(
            self.secret.encode(), f"{kind}:{value}".encode(), hashlib.sha256
        ).hexdigest()[:24]
        token = f"tok_{kind}_{digest}"
        self._reverse[token] = value
        return token

    def detokenise(self, token: str, *, reason: str) -> str | None:
        """Reverse a token. Every call is logged with a stated reason.

        Detokenisation is a privileged operation, so the reason is a required
        argument rather than an optional one — an unexplained reversal should be
        impossible to write, not merely discouraged.
        """
        self._access_log.append((token, reason))
        return self._reverse.get(token)

    @property
    def access_log(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._access_log)


DEFAULT_VAULT = TokenisationVault()
