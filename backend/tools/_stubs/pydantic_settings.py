"""Minimal stand-in for pydantic-settings.

Used ONLY by the offline Pyodide harness (tools/mkharness.sh), where the real
package is unavailable. Never imported in a deployed environment: production
installs pydantic-settings from requirements.txt and this directory is not on
the path.
"""

from __future__ import annotations

import os
import typing


class SettingsConfigDict(dict):
    def __init__(self, **kw):
        super().__init__(**kw)


class BaseSettings:
    model_config: dict = {}

    def __init__(self, **overrides):
        cfg = getattr(type(self), "model_config", {}) or {}
        prefix = cfg.get("env_prefix", "")
        try:
            hints = typing.get_type_hints(type(self))
        except Exception:
            hints = {}
        for name, typ in hints.items():
            if name.startswith("_") or name == "model_config":
                continue
            default = getattr(type(self), name, None)
            env = os.environ.get(prefix + name.upper())
            if name in overrides:
                value = overrides[name]
            elif env is not None:
                value = _coerce(env, typ)
            else:
                value = default
            setattr(self, name, value)


def _coerce(raw: str, typ):
    try:
        if typ is bool:
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        if typ is int:
            return int(raw)
        if typ is float:
            return float(raw)
    except Exception:
        pass
    return raw
