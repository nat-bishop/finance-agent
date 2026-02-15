"""Agent and trading configuration via Pydantic settings."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings

_TOML_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "config.toml",  # repo root
    Path("/app/config.toml"),  # Docker
]


def _load_profile(profile: str) -> dict:
    """Read a named profile from config.toml, return its values as a dict."""
    for path in _TOML_CANDIDATES:
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            if profile in data:
                return data[profile]
            break
    return {}


class TradingConfig(BaseSettings):
    """Domain configuration for Kalshi trading."""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = "/workspace/keys/private_key.pem"
    kalshi_env: Literal["demo", "prod"] = "demo"

    kalshi_max_position_usd: float = 50.0
    max_portfolio_usd: float = 500.0
    max_order_count: int = 100
    min_edge_pct: float = 5.0
    kalshi_fee_rate: float = 0.03

    db_path: str = "/workspace/data/agent.db"
    backup_dir: str = "/workspace/backups"
    backup_max_age_hours: int = 24
    kalshi_rate_limit_reads_per_sec: int = 20  # Kalshi Basic tier
    kalshi_rate_limit_writes_per_sec: int = 10  # Kalshi Basic tier
    polymarket_rate_limit_reads_per_sec: int = 15  # tightest: /positions (150/10s)
    polymarket_rate_limit_writes_per_sec: int = 50  # tightest: DELETE /order (500/10s)
    auto_scan_on_startup: bool = True

    # Polymarket credentials
    polymarket_key_id: str = ""
    polymarket_secret_key: str = ""
    polymarket_enabled: bool = False

    # Polymarket limits & fees
    polymarket_fee_rate: float = 0.0  # 0% maker, 0% taker on Polymarket US
    polymarket_max_position_usd: float = 50.0

    @property
    def polymarket_api_url(self) -> str:
        return "https://api.polymarket.us"

    @property
    def polymarket_gateway_url(self) -> str:
        return "https://gateway.polymarket.us"

    @property
    def kalshi_base_url(self) -> str:
        if self.kalshi_env == "prod":
            return "https://api.elections.kalshi.com"
        return "https://demo-api.kalshi.co"

    @property
    def kalshi_api_url(self) -> str:
        return f"{self.kalshi_base_url}/trade-api/v2"


class AgentConfig(BaseSettings):
    """SDK-level agent configuration."""

    model_config = {"env_prefix": "AGENT_", "env_file": ".env", "extra": "ignore"}

    name: str = "arb-agent"
    profile: str = "demo"
    model: str = "claude-sonnet-4-5-20250929"
    max_budget_usd: float = 1.0
    permission_mode: str = "acceptEdits"


def load_configs() -> tuple[AgentConfig, TradingConfig]:
    """Build AgentConfig and TradingConfig with TOML profile defaults.

    Priority: env vars / .env > TOML profile values > class defaults.

    Pydantic BaseSettings reads env vars automatically, so we only inject
    TOML values for fields that weren't set by env vars.  We detect which
    fields were explicitly set by comparing a bare BaseSettings instance
    (env-only) against its class defaults.
    """
    # First pass: resolve profile name from env
    agent_pre = AgentConfig()
    profile_defaults = _load_profile(agent_pre.profile)

    # Split TOML keys into agent-level vs trading-level
    agent_keys = set(AgentConfig.model_fields)
    trading_toml = {
        k: v
        for k, v in profile_defaults.items()
        if k not in agent_keys and k in TradingConfig.model_fields
    }
    agent_toml = {k: v for k, v in profile_defaults.items() if k in agent_keys}

    # For each config class, only apply TOML value if env didn't set the field.
    # We detect "env set" by checking if the env-loaded value differs from the
    # class default.  If it does, the user explicitly set it via env.
    def _merge(cls: type[BaseSettings], toml_vals: dict) -> dict:
        env_instance = cls()
        merged: dict = {}
        for key, toml_val in toml_vals.items():
            field_default = cls.model_fields[key].default
            env_val = getattr(env_instance, key)
            # If env value matches class default, no env override → use TOML
            if env_val == field_default:
                merged[key] = toml_val
        return merged

    trading_config = TradingConfig(**_merge(TradingConfig, trading_toml))
    agent_config = AgentConfig(**_merge(AgentConfig, agent_toml))

    return agent_config, trading_config


def load_prompt(name: str) -> str:
    """Load a prompt template from src/finance_agent/prompts/."""
    prompt_dir = Path(__file__).parent / "prompts"
    return (prompt_dir / f"{name}.md").read_text(encoding="utf-8")


def build_system_prompt(trading_config: TradingConfig) -> str:
    """Load system.md and substitute {{VARIABLE}} placeholders from config."""
    raw = load_prompt("system")
    variables = {
        "KALSHI_MAX_POSITION_USD": trading_config.kalshi_max_position_usd,
        "MAX_PORTFOLIO_USD": trading_config.max_portfolio_usd,
        "MAX_ORDER_COUNT": trading_config.max_order_count,
        "MIN_EDGE_PCT": trading_config.min_edge_pct,
        "KALSHI_FEE_RATE": trading_config.kalshi_fee_rate,
        "KALSHI_ENV": trading_config.kalshi_env,
        "POLYMARKET_FEE_RATE": trading_config.polymarket_fee_rate,
        "POLYMARKET_MAX_POSITION_USD": trading_config.polymarket_max_position_usd,
        "POLYMARKET_ENABLED": trading_config.polymarket_enabled,
    }
    for name, value in variables.items():
        raw = raw.replace(f"{{{{{name}}}}}", str(value))
    return raw
