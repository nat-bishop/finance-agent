"""Tests for finance_agent.tools -- MCP tool factories."""

from __future__ import annotations

import json

from finance_agent.tools import _text, create_db_tools, create_market_tools


def _call(tool_list, index):
    """Get the handler function from an SdkMcpTool at the given index."""
    return tool_list[index].handler


# ── _text helper ─────────────────────────────────────────────────


def test_text_wraps_as_mcp_content():
    result = _text({"key": "val"})
    assert result["content"][0]["type"] == "text"
    parsed = json.loads(result["content"][0]["text"])
    assert parsed == {"key": "val"}


def test_text_handles_non_serializable():
    from datetime import UTC, datetime

    result = _text({"dt": datetime(2025, 1, 1, tzinfo=UTC)})
    text = result["content"][0]["text"]
    assert "2025" in text


# ── Market tools ─────────────────────────────────────────────────


async def test_get_market(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    await _call(tools, 0)({"market_id": "K-MKT-1"})
    mock_kalshi.get_market.assert_called_once_with("K-MKT-1")


async def test_get_orderbook(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    await _call(tools, 1)({"market_id": "K-MKT-1", "depth": 5})
    mock_kalshi.get_orderbook.assert_called_once_with("K-MKT-1", depth=5)


async def test_get_trades(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    await _call(tools, 2)({"market_id": "K-MKT-1", "limit": 20})
    mock_kalshi.get_trades.assert_called_once_with("K-MKT-1", limit=20)


async def test_get_portfolio(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    result = await _call(tools, 3)({})
    parsed = json.loads(result["content"][0]["text"])
    assert "balance" in parsed
    assert "positions" in parsed
    mock_kalshi.get_balance.assert_called_once()
    mock_kalshi.get_positions.assert_called_once()


async def test_get_portfolio_with_fills(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    await _call(tools, 3)({"include_fills": True})
    mock_kalshi.get_fills.assert_called_once()


async def test_get_orders(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    result = await _call(tools, 4)({"market_id": "K-MKT-1"})
    parsed = json.loads(result["content"][0]["text"])
    assert parsed is not None
    mock_kalshi.get_orders.assert_called_once()


# ── DB tools: bracket strategy ───────────────────────────────────


def _bracket_mocks(mock_kalshi):
    """Set up orderbooks with a profitable bracket arb (YES sum < 100c)."""
    from unittest.mock import AsyncMock

    # 3-leg bracket: YES prices 30 + 30 + 30 = 90c → 10c edge per set
    mock_kalshi.get_orderbook = AsyncMock(
        side_effect=[
            {"yes": [[30, 100]], "no": [[70, 100]]},
            {"yes": [[30, 100]], "no": [[70, 100]]},
            {"yes": [[30, 100]], "no": [[70, 100]]},
        ]
    )
    mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Test Kalshi Market"}})


async def test_recommend_trade_bracket(db, session_id, mock_kalshi):
    from finance_agent.config import TradingConfig

    _bracket_mocks(mock_kalshi)
    cfg = TradingConfig(min_edge_pct=0.0)
    tools = create_db_tools(
        db,
        session_id,
        mock_kalshi,
        trading_config=cfg,
        recommendation_ttl_minutes=30,
    )
    result = await _call(tools, 0)(
        {
            "thesis": "Bracket arb on 3-outcome event, YES sum 90c vs 100c payout",
            "strategy": "bracket",
            "total_exposure_usd": 50.0,
            "legs": [
                {"market_id": "K-1"},
                {"market_id": "K-2"},
                {"market_id": "K-3"},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0
    assert data["expires_at"] is not None
    assert "computed" in data
    assert data["computed"]["contracts_per_leg"] > 0


async def test_recommend_trade_bracket_creates_group(db, session_id, mock_kalshi):
    from finance_agent.config import TradingConfig

    _bracket_mocks(mock_kalshi)
    cfg = TradingConfig(min_edge_pct=0.0)
    tools = create_db_tools(db, session_id, mock_kalshi, trading_config=cfg)
    await _call(tools, 0)(
        {
            "thesis": "Bracket arb: 3 mutually exclusive outcomes sum to 90c",
            "strategy": "bracket",
            "total_exposure_usd": 50.0,
            "legs": [
                {"market_id": "K-1"},
                {"market_id": "K-2"},
                {"market_id": "K-3"},
            ],
        }
    )
    groups = db.get_pending_groups()
    assert len(groups) == 1
    assert len(groups[0]["legs"]) == 3
    assert all(leg["exchange"] == "kalshi" for leg in groups[0]["legs"])
    assert groups[0]["computed_edge_pct"] is not None
    assert groups[0]["computed_fees_usd"] is not None
    assert groups[0]["total_exposure_usd"] == 50.0


async def test_recommend_trade_bracket_ttl(db, session_id, mock_kalshi):
    from unittest.mock import AsyncMock

    from finance_agent.config import TradingConfig

    def _fresh_mocks():
        mock_kalshi.get_orderbook = AsyncMock(
            side_effect=[
                {"yes": [[30, 100]], "no": [[70, 100]]},
                {"yes": [[30, 100]], "no": [[70, 100]]},
                {"yes": [[30, 100]], "no": [[70, 100]]},
            ]
        )
        mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Test Market"}})

    cfg = TradingConfig(min_edge_pct=0.0)

    _fresh_mocks()
    tools_30 = create_db_tools(
        db, session_id, mock_kalshi, trading_config=cfg, recommendation_ttl_minutes=30
    )
    r1 = await _call(tools_30, 0)(
        {
            "thesis": "Short TTL bracket arb opportunity test",
            "strategy": "bracket",
            "total_exposure_usd": 50.0,
            "legs": [{"market_id": "K-1"}, {"market_id": "K-2"}, {"market_id": "K-3"}],
        }
    )

    _fresh_mocks()
    tools_120 = create_db_tools(
        db, session_id, mock_kalshi, trading_config=cfg, recommendation_ttl_minutes=120
    )
    r2 = await _call(tools_120, 0)(
        {
            "thesis": "Long TTL bracket arb opportunity test",
            "strategy": "bracket",
            "total_exposure_usd": 50.0,
            "legs": [{"market_id": "K-1"}, {"market_id": "K-2"}, {"market_id": "K-3"}],
        }
    )
    d1 = json.loads(r1["content"][0]["text"])
    d2 = json.loads(r2["content"][0]["text"])
    assert d1["expires_at"] < d2["expires_at"]


async def test_recommend_trade_bracket_requires_exposure(db, session_id, mock_kalshi):
    tools = create_db_tools(db, session_id, mock_kalshi)
    result = await _call(tools, 0)(
        {
            "thesis": "Missing exposure should fail",
            "strategy": "bracket",
            "legs": [{"market_id": "K-1"}, {"market_id": "K-2"}, {"market_id": "K-3"}],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data


# ── DB tools: manual strategy ────────────────────────────────────


def _manual_mocks(mock_kalshi):
    """Set up orderbooks for manual strategy tests."""
    from unittest.mock import AsyncMock

    mock_kalshi.get_orderbook = AsyncMock(
        side_effect=[
            {"yes": [[45, 100]], "no": [[55, 100]]},
            {"yes": [[52, 100]], "no": [[48, 100]]},
        ]
    )
    mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Test Manual Market"}})


async def test_recommend_trade_manual(db, session_id, mock_kalshi):
    _manual_mocks(mock_kalshi)
    tools = create_db_tools(db, session_id, mock_kalshi)
    result = await _call(tools, 0)(
        {
            "thesis": "Correlated markets: price divergence detected in same category",
            "equivalence_notes": "Both markets track the same underlying outcome",
            "strategy": "manual",
            "legs": [
                {"market_id": "K-1", "action": "buy", "side": "yes", "quantity": 10},
                {"market_id": "K-2", "action": "sell", "side": "yes", "quantity": 10},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0
    assert data["strategy"] == "manual"
    assert "computed" in data
    assert data["computed"]["total_cost_usd"] > 0


async def test_recommend_trade_manual_requires_action_side(db, session_id, mock_kalshi):
    _manual_mocks(mock_kalshi)
    tools = create_db_tools(db, session_id, mock_kalshi)
    result = await _call(tools, 0)(
        {
            "thesis": "Missing action/side should fail for manual strategy",
            "strategy": "manual",
            "legs": [
                {"market_id": "K-1"},
                {"market_id": "K-2"},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data
    assert "action" in data["error"].lower() or "side" in data["error"].lower()


async def test_recommend_trade_manual_aggregate_limit(db, session_id, mock_kalshi):
    """Manual strategy should reject when aggregate exposure exceeds limit."""
    from unittest.mock import AsyncMock

    mock_kalshi.get_orderbook = AsyncMock(
        side_effect=[
            {"yes": [[50, 500]], "no": [[50, 500]]},
            {"yes": [[50, 500]], "no": [[50, 500]]},
        ]
    )
    mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Test Market"}})
    from finance_agent.config import TradingConfig

    cfg = TradingConfig(kalshi_max_position_usd=20.0, min_edge_pct=0.0)
    tools = create_db_tools(db, session_id, mock_kalshi, trading_config=cfg)
    result = await _call(tools, 0)(
        {
            "thesis": "This should exceed aggregate limits",
            "strategy": "manual",
            "legs": [
                {"market_id": "K-1", "action": "buy", "side": "yes", "quantity": 50},
                {"market_id": "K-2", "action": "buy", "side": "yes", "quantity": 50},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data


# ── Tool count verification ──────────────────────────────────────


def test_market_tools_count(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    assert len(tools) == 5


def test_db_tools_count(db, session_id, mock_kalshi):
    tools = create_db_tools(db, session_id, mock_kalshi)
    assert len(tools) == 1
