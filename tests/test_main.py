"""Tests for finance_agent.main -- entry point and setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from finance_agent.main import build_options

# ── build_options ────────────────────────────────────────────────


def test_build_options_returns_options(db, session_id):
    agent_config = MagicMock()
    agent_config.model = "claude-sonnet-4-5-20250929"
    agent_config.max_budget_usd = 1.0
    trading_config = MagicMock()

    with patch("finance_agent.main.build_system_prompt", return_value="test prompt"):
        result = build_options(
            agent_config,
            trading_config,
            mcp_servers={},
            can_use_tool=lambda *a: None,
            hooks={},
        )
    assert result.model == "claude-sonnet-4-5-20250929"
    assert result.permission_mode == "acceptEdits"
