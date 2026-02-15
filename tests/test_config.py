"""Tests for finance_agent.config -- configuration management."""

from __future__ import annotations

import re

from finance_agent.config import (
    AgentConfig,
    TradingConfig,
    build_system_prompt,
    load_configs,
    load_prompt,
)

# ── TradingConfig defaults ───────────────────────────────────────


def test_trading_config_defaults(monkeypatch):
    # Clear env vars that might interfere
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)

    config = TradingConfig()
    assert config.kalshi_fee_rate == 0.03
    assert config.polymarket_fee_rate == 0.0
    assert config.recommendation_ttl_minutes == 60
    assert config.kalshi_max_position_usd == 100.0
    assert config.max_portfolio_usd == 1000.0
    assert config.max_order_count == 50
    assert config.min_edge_pct == 7.0
    assert config.polymarket_enabled is False


def test_trading_config_urls(monkeypatch):
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)

    config = TradingConfig()
    assert "elections" in config.kalshi_base_url
    assert config.kalshi_api_url.endswith("/trade-api/v2")


def test_polymarket_urls(monkeypatch):
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)

    config = TradingConfig()
    assert config.polymarket_api_url == "https://api.polymarket.us"
    assert config.polymarket_gateway_url == "https://gateway.polymarket.us"


# ── AgentConfig defaults ─────────────────────────────────────────


def test_agent_config_defaults(monkeypatch):
    for key in list(AgentConfig.model_fields):
        monkeypatch.delenv(f"AGENT_{key.upper()}", raising=False)
        monkeypatch.delenv(key.upper(), raising=False)

    config = AgentConfig()
    assert config.name == "arb-agent"
    assert config.max_budget_usd == 2.0
    assert "sonnet" in config.model


# ── load_configs ─────────────────────────────────────────────────


def test_load_configs_returns_tuple(monkeypatch):
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)
    for key in list(AgentConfig.model_fields):
        monkeypatch.delenv(f"AGENT_{key.upper()}", raising=False)

    agent_config, trading_config = load_configs()
    assert isinstance(agent_config, AgentConfig)
    assert isinstance(trading_config, TradingConfig)


# ── build_system_prompt ──────────────────────────────────────────


def test_build_system_prompt_substitutes(monkeypatch):
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)

    config = TradingConfig()
    prompt = build_system_prompt(config)
    assert "100.0" in prompt  # KALSHI_MAX_POSITION_USD
    assert "0.03" in prompt  # KALSHI_FEE_RATE


def test_build_system_prompt_no_unresolved_placeholders(monkeypatch):
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)

    config = TradingConfig()
    prompt = build_system_prompt(config)
    # No {{VARIABLE}} patterns should remain
    assert not re.search(r"\{\{[A-Z_]+\}\}", prompt)


# ── load_prompt ──────────────────────────────────────────────────


def test_load_prompt_system():
    text = load_prompt("system")
    assert len(text) > 100
