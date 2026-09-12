"""Central configuration for ARTHA.

Every tunable that affects a lending decision lives here rather than being
scattered through the engines, because the Suitability Gate's thresholds are
themselves a regulated artefact: a supervisor is entitled to ask what the
buffer floor was on a given date, and the answer has to come from one place
that is versioned alongside the decision log.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARTHA_", env_file=".env", extra="ignore"
    )

    env: str = "dev"

    # --- persistence -------------------------------------------------------
    database_url: str = "sqlite:///./artha.db"
    vault_secret: str = "dev-only-insecure-secret-replace-me"

    # --- Financial Twin (report §5.1) --------------------------------------
    twin_horizon_days: int = 180          # "the next six months"
    twin_paths: int = 2000                # Monte-Carlo paths per candidate
    twin_seed: int = 20260912             # fixed: a decision must be reproducible

    # --- Suitability Gate (report §5.2) ------------------------------------
    nudge_budget_per_month: int = 4
    product_cooldown_days: int = 45
    min_buffer_days: int = 21             # safe buffer expressed in days of outflow
    breach_probability_ceiling: float = 0.10
    obligation_to_income_ceiling: float = 0.50

    # --- Sentinel / banker console (report §6.3) ---------------------------
    daily_contact_capacity: int = 150
    correlated_alert_min_cluster: int = 25

    # --- Language services (report §7.5) -----------------------------------
    language_provider: str = "stub"       # stub | bhashini
    bhashini_endpoint: str = ""
    bhashini_api_key: str = ""

    # --- AI Firewall (report §7.7) -----------------------------------------
    # Absolute, in rupees. Rendering rounds to the rupee; nothing else is
    # tolerated, because a relative band would let a model state an amount half
    # a percent off and pass the check that exists to stop exactly that.
    firewall_numeric_tolerance_rupees: float = 1.0
    capability_token_ttl_seconds: int = 300


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
