"""Stable seeding.

Python salts `hash()` of strings per interpreter process, so
`abs(hash(("seed", token))) % 2**32` produces a *different* value on every run.
Anything seeded that way is reproducible within one process and irreproducible
across two.

That is fatal to two claims this system makes:

* report §11.2 — the illustrative figures must reproduce, or the claims register
  means nothing;
* report §7.6 and §8 — a lending decision must be reconstructable on demand. An
  auditor asking why a customer was refused in March has to be able to re-run
  March's simulation and obtain March's answer.

:func:`stable_seed` is a content hash, so the same inputs give the same seed on
any machine, in any process, forever.
"""

from __future__ import annotations

import hashlib

_MASK = (1 << 32) - 1


def stable_seed(*parts: object) -> int:
    """A deterministic 32-bit seed derived from the string form of ``parts``."""
    blob = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2s(blob, digest_size=4).digest(), "big") & _MASK


def stable_index(n: int, *parts: object) -> int:
    """A deterministic index into a sequence of length ``n``."""
    if n <= 0:
        raise ValueError("n must be positive")
    return stable_seed(*parts) % n
