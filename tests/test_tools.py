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


# ── DB tools: recommend_trade ────────────────────────────────────


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
            "legs": [
                {"market_id": "K-1", "action": "buy", "side": "yes", "quantity": 10},
                {"market_id": "K-2", "action": "sell", "side": "yes", "quantity": 10},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0
    assert "computed" in data
    assert data["computed"]["total_cost_usd"] > 0


async def test_recommend_trade_manual_requires_action_side(db, session_id, mock_kalshi):
    _manual_mocks(mock_kalshi)
    tools = create_db_tools(db, session_id, mock_kalshi)
    result = await _call(tools, 0)(
        {
            "thesis": "Missing action/side should fail for recommendation",
            "legs": [
                {"market_id": "K-1"},
                {"market_id": "K-2"},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data
    assert "action" in data["error"].lower() or "side" in data["error"].lower()


async def test_recommend_trade_manual_sell(db, session_id, mock_kalshi):
    """Sell orders should use bid prices (100 - opposite ask), not ask prices."""
    from unittest.mock import AsyncMock

    # yes_ask=45, no_ask=55 → yes_bid = 100-55 = 45, no_bid = 100-45 = 55
    # yes_ask=60, no_ask=40 → yes_bid = 100-40 = 60, no_bid = 100-60 = 40
    mock_kalshi.get_orderbook = AsyncMock(
        side_effect=[
            {"yes": [[45, 100]], "no": [[55, 100]]},
            {"yes": [[60, 100]], "no": [[40, 100]]},
        ]
    )
    mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Test Sell Market"}})

    tools = create_db_tools(db, session_id, mock_kalshi)
    result = await _call(tools, 0)(
        {
            "thesis": "Sell-side strategy: sell YES on overpriced market, buy YES on underpriced",
            "legs": [
                {"market_id": "K-1", "action": "sell", "side": "yes", "quantity": 5},
                {"market_id": "K-2", "action": "buy", "side": "yes", "quantity": 5},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0

    # Verify the sell leg uses bid price (100 - no_ask = 100 - 55 = 45)
    sell_leg = next(lg for lg in data["legs"] if lg["action"] == "sell")
    assert sell_leg["price_cents"] == 45  # yes_bid = 100 - no_ask(55) = 45

    # Verify the buy leg uses ask price (60)
    buy_leg = next(lg for lg in data["legs"] if lg["action"] == "buy")
    assert buy_leg["price_cents"] == 60  # yes_ask = 60


async def test_recommend_trade_manual_aggregate_limit(db, session_id, mock_kalshi):
    """Should reject when aggregate exposure exceeds limit."""
    from unittest.mock import AsyncMock

    mock_kalshi.get_orderbook = AsyncMock(
        side_effect=[
            {"yes": [[50, 500]], "no": [[50, 500]]},
            {"yes": [[50, 500]], "no": [[50, 500]]},
        ]
    )
    mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Test Market"}})
    from finance_agent.config import TradingConfig

    cfg = TradingConfig(kalshi_max_position_usd=20.0)
    tools = create_db_tools(db, session_id, mock_kalshi, trading_config=cfg)
    result = await _call(tools, 0)(
        {
            "thesis": "This should exceed aggregate limits",
            "legs": [
                {"market_id": "K-1", "action": "buy", "side": "yes", "quantity": 50},
                {"market_id": "K-2", "action": "buy", "side": "yes", "quantity": 50},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data


async def test_recommend_trade_stores_strategy_manual(db, session_id, mock_kalshi):
    """Recommendations should store strategy='manual' in DB."""
    _manual_mocks(mock_kalshi)
    tools = create_db_tools(db, session_id, mock_kalshi)
    await _call(tools, 0)(
        {
            "thesis": "Strategy stored in DB as manual",
            "legs": [
                {"market_id": "K-1", "action": "buy", "side": "yes", "quantity": 10},
                {"market_id": "K-2", "action": "buy", "side": "yes", "quantity": 10},
            ],
        }
    )
    groups = db.get_pending_groups()
    assert groups[0]["strategy"] == "manual"


async def test_recommend_trade_single_leg(db, session_id, mock_kalshi):
    """Single-leg recommendations should work (minItems=1)."""
    from unittest.mock import AsyncMock

    mock_kalshi.get_orderbook = AsyncMock(return_value={"yes": [[45, 100]], "no": [[55, 100]]})
    mock_kalshi.get_market = AsyncMock(return_value={"market": {"title": "Single Leg Market"}})

    tools = create_db_tools(db, session_id, mock_kalshi)
    result = await _call(tools, 0)(
        {
            "thesis": "Single leg trade recommendation on underpriced market",
            "legs": [
                {"market_id": "K-1", "action": "buy", "side": "yes", "quantity": 10},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0
    assert "computed" in data
    assert len(data["legs"]) == 1
    assert data["legs"][0]["market_id"] == "K-1"

    groups = db.get_pending_groups()
    assert len(groups) == 1
    assert len(groups[0]["legs"]) == 1


# ── Tool count verification ──────────────────────────────────────


def test_market_tools_count(mock_kalshi):
    tools = create_market_tools(mock_kalshi)
    assert len(tools) == 5


def test_db_tools_count(db, session_id, mock_kalshi):
    tools = create_db_tools(db, session_id, mock_kalshi)
    assert len(tools) == 1
