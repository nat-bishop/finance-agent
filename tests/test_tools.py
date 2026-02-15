"""Tests for finance_agent.tools -- MCP tool factories."""

from __future__ import annotations

import json

import pytest

from finance_agent.tools import _require_exchange, _text, create_db_tools, create_market_tools


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
    from datetime import datetime

    result = _text({"dt": datetime(2025, 1, 1)})
    text = result["content"][0]["text"]
    assert "2025" in text


# ── _require_exchange ────────────────────────────────────────────


def test_require_exchange_kalshi():
    assert _require_exchange({"exchange": "kalshi"}, None) == "kalshi"


def test_require_exchange_polymarket():
    from unittest.mock import MagicMock

    pm = MagicMock()
    assert _require_exchange({"exchange": "polymarket"}, pm) == "polymarket"


def test_require_exchange_invalid():
    with pytest.raises(ValueError, match="exchange must be"):
        _require_exchange({"exchange": "binance"}, None)


def test_require_exchange_polymarket_disabled():
    with pytest.raises(ValueError, match="not enabled"):
        _require_exchange({"exchange": "polymarket"}, None)


def test_require_exchange_case_insensitive():
    assert _require_exchange({"exchange": "Kalshi"}, None) == "kalshi"


# ── Market tools ─────────────────────────────────────────────────


async def test_search_markets_both(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    result = await _call(tools, 0)({"query": "test"})
    parsed = json.loads(result["content"][0]["text"])
    assert "kalshi" in parsed
    assert "polymarket" in parsed


async def test_search_markets_kalshi_only(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 0)({"exchange": "kalshi", "query": "test"})
    mock_kalshi.search_markets.assert_called_once()
    mock_polymarket.search_markets.assert_not_called()


async def test_search_markets_no_polymarket(mock_kalshi):
    tools = create_market_tools(mock_kalshi, None)
    result = await _call(tools, 0)({"query": "test"})
    parsed = json.loads(result["content"][0]["text"])
    assert "kalshi" in parsed
    assert "polymarket" not in parsed


async def test_get_market_kalshi(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 1)({"exchange": "kalshi", "market_id": "K-MKT-1"})
    mock_kalshi.get_market.assert_called_once_with("K-MKT-1")


async def test_get_market_polymarket(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 1)({"exchange": "polymarket", "market_id": "test-slug"})
    mock_polymarket.get_market.assert_called_once_with("test-slug")


async def test_get_orderbook_polymarket_bbo(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 2)({"exchange": "polymarket", "market_id": "slug", "depth": 1})
    mock_polymarket.get_bbo.assert_called_once_with("slug")
    mock_polymarket.get_orderbook.assert_not_called()


async def test_get_orderbook_polymarket_full(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 2)({"exchange": "polymarket", "market_id": "slug", "depth": 5})
    mock_polymarket.get_orderbook.assert_called_once_with("slug")


async def test_get_price_history_kalshi(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 4)({"market_id": "K-MKT-1"})
    mock_kalshi.get_candlesticks.assert_called_once()


async def test_get_portfolio_both(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    result = await _call(tools, 6)({})
    parsed = json.loads(result["content"][0]["text"])
    assert "kalshi" in parsed
    assert "polymarket" in parsed
    mock_kalshi.get_balance.assert_called_once()
    mock_polymarket.get_balance.assert_called_once()


async def test_get_portfolio_with_fills(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    await _call(tools, 6)({"exchange": "kalshi", "include_fills": True})
    mock_kalshi.get_fills.assert_called_once()


async def test_get_orders_both(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    result = await _call(tools, 7)({})
    parsed = json.loads(result["content"][0]["text"])
    assert "kalshi" in parsed
    assert "polymarket" in parsed


# ── DB tools ─────────────────────────────────────────────────────


async def test_recommend_trade_tool(db, session_id):
    tools = create_db_tools(db, session_id, recommendation_ttl_minutes=30)
    result = await _call(tools, 0)(
        {
            "thesis": "Cross-platform arbitrage on presidential election",
            "estimated_edge_pct": 7.5,
            "equivalence_notes": "Both resolve based on AP call, same timing",
            "legs": [
                {
                    "exchange": "kalshi",
                    "market_id": "K-MKT-1",
                    "market_title": "Test Market Kalshi",
                    "action": "buy",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 45,
                },
                {
                    "exchange": "polymarket",
                    "market_id": "PM-MKT-1",
                    "market_title": "Test Market PM",
                    "action": "sell",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 52,
                },
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0
    assert data["leg_count"] == 2
    assert data["expires_at"] is not None


async def test_recommend_trade_creates_group_with_legs(db, session_id):
    tools = create_db_tools(db, session_id)
    await _call(tools, 0)(
        {
            "thesis": "Bracket arb: prices sum to 112",
            "estimated_edge_pct": 6.0,
            "equivalence_notes": "Same mutually exclusive event, verified resolution source",
            "legs": [
                {
                    "exchange": "kalshi",
                    "market_id": "K-1",
                    "market_title": "Leg 1",
                    "action": "buy",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 45,
                },
                {
                    "exchange": "polymarket",
                    "market_id": "PM-1",
                    "market_title": "Leg 2",
                    "action": "sell",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 52,
                },
            ],
        }
    )
    groups = db.get_pending_groups()
    assert len(groups) == 1
    assert len(groups[0]["legs"]) == 2
    assert groups[0]["legs"][0]["exchange"] == "kalshi"
    assert groups[0]["legs"][1]["exchange"] == "polymarket"


async def test_recommend_trade_ttl_override(db, session_id):
    tools_30 = create_db_tools(db, session_id, recommendation_ttl_minutes=30)
    tools_120 = create_db_tools(db, session_id, recommendation_ttl_minutes=120)

    leg_pair = [
        {
            "exchange": "kalshi",
            "market_id": "K-1",
            "market_title": "T1",
            "action": "buy",
            "side": "yes",
            "quantity": 10,
            "price_cents": 45,
        },
        {
            "exchange": "polymarket",
            "market_id": "PM-1",
            "market_title": "T2",
            "action": "sell",
            "side": "yes",
            "quantity": 10,
            "price_cents": 52,
        },
    ]

    r1 = await _call(tools_30, 0)(
        {
            "thesis": "Short TTL arb opportunity test",
            "estimated_edge_pct": 5.0,
            "equivalence_notes": "Verified same resolution",
            "legs": leg_pair,
        }
    )
    r2 = await _call(tools_120, 0)(
        {
            "thesis": "Long TTL arb opportunity test",
            "estimated_edge_pct": 5.0,
            "equivalence_notes": "Verified same resolution",
            "legs": leg_pair,
        }
    )
    d1 = json.loads(r1["content"][0]["text"])
    d2 = json.loads(r2["content"][0]["text"])
    assert d1["expires_at"] < d2["expires_at"]


async def test_recommend_trade_warns_on_missing_equivalence(db, session_id):
    tools = create_db_tools(db, session_id)
    result = await _call(tools, 0)(
        {
            "thesis": "Missing equivalence notes test",
            "estimated_edge_pct": 5.0,
            "equivalence_notes": "",
            "legs": [
                {
                    "exchange": "kalshi",
                    "market_id": "K-1",
                    "market_title": "L1",
                    "action": "buy",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 45,
                },
                {
                    "exchange": "polymarket",
                    "market_id": "PM-1",
                    "market_title": "L2",
                    "action": "sell",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 52,
                },
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "warnings" in data


# ── Tool count verification ──────────────────────────────────────


def test_market_tools_count(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    assert len(tools) == 8


def test_db_tools_count(db, session_id):
    tools = create_db_tools(db, session_id)
    assert len(tools) == 1
