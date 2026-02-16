"""Tests for finance_agent.config -- configuration management."""

from __future__ import annotations

import re

from finance_agent.config import (
    AgentConfig,
    Credentials,
    TradingConfig,
    build_system_prompt,
    load_configs,
    load_prompt,
)

# ── TradingConfig defaults ───────────────────────────────────────


def test_trading_config_defaults():
    config = TradingConfig()
    assert config.recommendation_ttl_minutes == 60
    assert config.kalshi_max_position_usd == 100.0
    assert config.max_portfolio_usd == 1000.0
    assert config.max_order_count == 50
    assert config.min_edge_pct == 7.0
    assert config.polymarket_enabled is True
    assert config.execution_timeout_seconds == 300
    assert config.max_slippage_cents == 3


def test_trading_config_urls():
    config = TradingConfig()
    assert "elections" in config.kalshi_base_url
    assert config.kalshi_api_url.endswith("/trade-api/v2")


# ── Credentials ──────────────────────────────────────────────────


def test_credentials_defaults(monkeypatch):
    # Set to empty — env vars take priority over .env file in pydantic-settings
    for key in Credentials.model_fields:
        monkeypatch.setenv(key.upper(), "")

    creds = Credentials()
    assert creds.kalshi_api_key_id == ""
    assert creds.polymarket_key_id == ""


# ── AgentConfig defaults ─────────────────────────────────────────


def test_agent_config_defaults():
    config = AgentConfig()
    assert config.max_budget_usd == 2.0
    assert "sonnet" in config.model


# ── load_configs ─────────────────────────────────────────────────


def test_load_configs_returns_tuple(monkeypatch):
    for key in Credentials.model_fields:
        monkeypatch.setenv(key.upper(), "")

    agent_config, credentials, trading_config = load_configs()
    assert isinstance(agent_config, AgentConfig)
    assert isinstance(credentials, Credentials)
    assert isinstance(trading_config, TradingConfig)


# ── build_system_prompt ──────────────────────────────────────────


def test_build_system_prompt_substitutes():
    config = TradingConfig()
    prompt = build_system_prompt(config)
    assert "100.0" in prompt  # KALSHI_MAX_POSITION_USD
    assert "300" in prompt  # EXECUTION_TIMEOUT_SECONDS


def test_build_system_prompt_no_unresolved_placeholders():
    config = TradingConfig()
    prompt = build_system_prompt(config)
    # No {{VARIABLE}} patterns should remain
    assert not re.search(r"\{\{[A-Z_]+\}\}", prompt)


# ── load_prompt ──────────────────────────────────────────────────


def test_load_prompt_system():
    text = load_prompt("system")
    assert len(text) > 100
