"""Agent and trading configuration via Pydantic settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class TradingConfig(BaseSettings):
    """Domain configuration for Kalshi trading."""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = "/workspace/keys/private_key.pem"

    kalshi_max_position_usd: float = 100.0
    max_portfolio_usd: float = 1000.0
    max_order_count: int = 50
    min_edge_pct: float = 7.0
    kalshi_fee_rate: float = 0.03

    db_path: str = "/workspace/data/agent.db"
    backup_dir: str = "/workspace/backups"
    backup_max_age_hours: int = 24
    kalshi_rate_limit_reads_per_sec: int = 20  # Kalshi Basic tier
    kalshi_rate_limit_writes_per_sec: int = 10  # Kalshi Basic tier
    polymarket_rate_limit_reads_per_sec: int = 15  # tightest: /positions (150/10s)
    polymarket_rate_limit_writes_per_sec: int = 50  # tightest: DELETE /order (500/10s)
    recommendation_ttl_minutes: int = 60

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
        return "https://api.elections.kalshi.com"

    @property
    def kalshi_api_url(self) -> str:
        return f"{self.kalshi_base_url}/trade-api/v2"


class AgentConfig(BaseSettings):
    """SDK-level agent configuration."""

    model_config = {"env_prefix": "AGENT_", "env_file": ".env", "extra": "ignore"}

    name: str = "arb-agent"
    model: str = "claude-sonnet-4-5-20250929"
    max_budget_usd: float = 2.0
    permission_mode: str = "acceptEdits"


def load_configs() -> tuple[AgentConfig, TradingConfig]:
    """Build AgentConfig and TradingConfig from env vars / .env file."""
    return AgentConfig(), TradingConfig()


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
        "POLYMARKET_FEE_RATE": trading_config.polymarket_fee_rate,
        "POLYMARKET_MAX_POSITION_USD": trading_config.polymarket_max_position_usd,
        "POLYMARKET_ENABLED": trading_config.polymarket_enabled,
        "RECOMMENDATION_TTL_MINUTES": trading_config.recommendation_ttl_minutes,
    }
    for name, value in variables.items():
        raw = raw.replace(f"{{{{{name}}}}}", str(value))
    return raw
