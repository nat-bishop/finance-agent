"""Tests for finance_agent.main -- entry point and setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from finance_agent.main import _init_watchlist, build_options

# ── _init_watchlist ──────────────────────────────────────────────


def test_init_watchlist_skips_if_exists(db, tmp_path):
    watchlist_path = tmp_path / "watchlist.md"
    watchlist_path.write_text("existing content")
    with patch("finance_agent.main._WATCHLIST_PATH", watchlist_path):
        _init_watchlist(db)
    assert watchlist_path.read_text() == "existing content"


def test_init_watchlist_writes_from_db(db, tmp_path):
    watchlist_path = tmp_path / "data" / "watchlist.md"
    # Add some watchlist entries to DB
    db.execute(
        "INSERT INTO watchlist (ticker, exchange, added_at, reason, alert_condition) "
        "VALUES (?, ?, ?, ?, ?)",
        ("K-MKT-1", "kalshi", "2025-01-01", "tracking", "price > 60"),
    )
    with patch("finance_agent.main._WATCHLIST_PATH", watchlist_path):
        _init_watchlist(db)
    content = watchlist_path.read_text()
    assert "# Watchlist" in content
    assert "K-MKT-1" in content
    assert "kalshi" in content


def test_init_watchlist_empty_db(db, tmp_path):
    watchlist_path = tmp_path / "data" / "watchlist.md"
    with patch("finance_agent.main._WATCHLIST_PATH", watchlist_path):
        _init_watchlist(db)
    content = watchlist_path.read_text()
    assert "# Watchlist" in content
    # No data rows, just header
    assert "Ticker" in content


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
