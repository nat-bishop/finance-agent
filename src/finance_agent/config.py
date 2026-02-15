"""Agent and trading configuration.

Credentials (API keys) load from .env / environment variables.
Everything else is a plain dataclass — edit this file to change defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings


class Credentials(BaseSettings):
    """API keys and secrets — loaded from .env / environment."""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    kalshi_api_key_id: str = ""
    kalshi_private_key: str = ""  # PEM content directly (newlines as \n)
    kalshi_private_key_path: str = "/workspace/keys/private_key.pem"
    polymarket_key_id: str = ""
    polymarket_secret_key: str = ""


@dataclass
class TradingConfig:
    """Trading parameters — edit this file to change."""

    kalshi_max_position_usd: float = 100.0
    max_portfolio_usd: float = 1000.0
    max_order_count: int = 50
    min_edge_pct: float = 7.0

    db_path: str = "/workspace/data/agent.db"
    backup_dir: str = "/workspace/backups"
    backup_max_age_hours: int = 24
    kalshi_rate_limit_reads_per_sec: int = 30  # Kalshi Basic tier
    kalshi_rate_limit_writes_per_sec: int = 30  # Kalshi Basic tier
    polymarket_rate_limit_reads_per_sec: int = 15  # tightest: /positions (150/10s)
    polymarket_rate_limit_writes_per_sec: int = 50  # tightest: DELETE /order (500/10s)
    recommendation_ttl_minutes: int = 60

    polymarket_enabled: bool = False
    polymarket_max_position_usd: float = 50.0

    execution_timeout_seconds: int = 300  # 5 min fill timeout for leg-in
    max_slippage_cents: int = 3  # reject execution if orderbook moved >N cents

    @property
    def kalshi_base_url(self) -> str:
        return "https://api.elections.kalshi.com"

    @property
    def kalshi_api_url(self) -> str:
        return f"{self.kalshi_base_url}/trade-api/v2"


@dataclass
class AgentConfig:
    """SDK-level agent configuration."""

    model: str = "claude-sonnet-4-5-20250929"
    max_budget_usd: float = 2.0


def load_configs() -> tuple[AgentConfig, Credentials, TradingConfig]:
    """Build configs. Credentials from env vars, everything else from defaults."""
    return AgentConfig(), Credentials(), TradingConfig()


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
        "POLYMARKET_MAX_POSITION_USD": trading_config.polymarket_max_position_usd,
        "POLYMARKET_ENABLED": trading_config.polymarket_enabled,
        "RECOMMENDATION_TTL_MINUTES": trading_config.recommendation_ttl_minutes,
        "EXECUTION_TIMEOUT_SECONDS": trading_config.execution_timeout_seconds,
        "MAX_SLIPPAGE_CENTS": trading_config.max_slippage_cents,
    }
    for name, value in variables.items():
        raw = raw.replace(f"{{{{{name}}}}}", str(value))
    return raw
