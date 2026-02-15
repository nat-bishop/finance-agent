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
    from datetime import UTC, datetime

    result = _text({"dt": datetime(2025, 1, 1, tzinfo=UTC)})
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


def _arb_mocks(mock_kalshi, mock_polymarket):
    """Set up orderbooks that produce a profitable arb (Kalshi YES=45, PM YES=52)."""
    mock_kalshi.get_orderbook.return_value = {"yes": [[45, 100]], "no": [[55, 100]]}
    mock_kalshi.get_market.return_value = {"market": {"title": "Test Kalshi Market"}}
    mock_polymarket.get_orderbook.return_value = {"yes": [[52, 100]], "no": [[48, 100]]}
    mock_polymarket.get_market.return_value = {"title": "Test PM Market"}


async def test_recommend_trade_tool(db, session_id, mock_kalshi, mock_polymarket):
    _arb_mocks(mock_kalshi, mock_polymarket)
    tools = create_db_tools(
        db, session_id, mock_kalshi, mock_polymarket, recommendation_ttl_minutes=30
    )
    result = await _call(tools, 0)(
        {
            "thesis": "Cross-platform arbitrage on presidential election",
            "equivalence_notes": "Both resolve based on AP call, same timing",
            "total_exposure_usd": 50.0,
            "legs": [
                {"exchange": "kalshi", "market_id": "K-MKT-1"},
                {"exchange": "polymarket", "market_id": "PM-MKT-1"},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert data["group_id"] > 0
    assert data["expires_at"] is not None
    assert "computed" in data
    assert data["computed"]["contracts_per_leg"] > 0


async def test_recommend_trade_creates_group_with_legs(
    db, session_id, mock_kalshi, mock_polymarket
):
    _arb_mocks(mock_kalshi, mock_polymarket)
    tools = create_db_tools(db, session_id, mock_kalshi, mock_polymarket)
    await _call(tools, 0)(
        {
            "thesis": "Cross-platform arb: price discrepancy detected",
            "equivalence_notes": "Same mutually exclusive event, verified resolution source",
            "total_exposure_usd": 50.0,
            "legs": [
                {"exchange": "kalshi", "market_id": "K-1"},
                {"exchange": "polymarket", "market_id": "PM-1"},
            ],
        }
    )
    groups = db.get_pending_groups()
    assert len(groups) == 1
    assert len(groups[0]["legs"]) == 2
    assert groups[0]["legs"][0]["exchange"] == "kalshi"
    assert groups[0]["legs"][1]["exchange"] == "polymarket"
    # Verify computed fields are populated
    assert groups[0]["computed_edge_pct"] is not None
    assert groups[0]["computed_fees_usd"] is not None
    assert groups[0]["total_exposure_usd"] == 50.0


async def test_recommend_trade_ttl_override(db, session_id, mock_kalshi, mock_polymarket):
    _arb_mocks(mock_kalshi, mock_polymarket)
    tools_30 = create_db_tools(
        db, session_id, mock_kalshi, mock_polymarket, recommendation_ttl_minutes=30
    )
    tools_120 = create_db_tools(
        db, session_id, mock_kalshi, mock_polymarket, recommendation_ttl_minutes=120
    )

    leg_pair = [
        {"exchange": "kalshi", "market_id": "K-1"},
        {"exchange": "polymarket", "market_id": "PM-1"},
    ]

    r1 = await _call(tools_30, 0)(
        {
            "thesis": "Short TTL arb opportunity test",
            "equivalence_notes": "Verified same resolution criteria match",
            "total_exposure_usd": 50.0,
            "legs": leg_pair,
        }
    )
    r2 = await _call(tools_120, 0)(
        {
            "thesis": "Long TTL arb opportunity test",
            "equivalence_notes": "Verified same resolution criteria match",
            "total_exposure_usd": 50.0,
            "legs": leg_pair,
        }
    )
    d1 = json.loads(r1["content"][0]["text"])
    d2 = json.loads(r2["content"][0]["text"])
    assert d1["expires_at"] < d2["expires_at"]


async def test_recommend_trade_rejects_missing_equivalence(
    db, session_id, mock_kalshi, mock_polymarket
):
    _arb_mocks(mock_kalshi, mock_polymarket)
    tools = create_db_tools(db, session_id, mock_kalshi, mock_polymarket)
    result = await _call(tools, 0)(
        {
            "thesis": "Missing equivalence notes test",
            "equivalence_notes": "",
            "total_exposure_usd": 50.0,
            "legs": [
                {"exchange": "kalshi", "market_id": "K-1"},
                {"exchange": "polymarket", "market_id": "PM-1"},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data


async def test_recommend_trade_rejects_same_exchange(db, session_id, mock_kalshi, mock_polymarket):
    _arb_mocks(mock_kalshi, mock_polymarket)
    tools = create_db_tools(db, session_id, mock_kalshi, mock_polymarket)
    result = await _call(tools, 0)(
        {
            "thesis": "Same exchange should fail",
            "equivalence_notes": "Verified resolution source matches exactly",
            "total_exposure_usd": 50.0,
            "legs": [
                {"exchange": "kalshi", "market_id": "K-1"},
                {"exchange": "kalshi", "market_id": "K-2"},
            ],
        }
    )
    data = json.loads(result["content"][0]["text"])
    assert "error" in data


# ── Tool count verification ──────────────────────────────────────


def test_market_tools_count(mock_kalshi, mock_polymarket):
    tools = create_market_tools(mock_kalshi, mock_polymarket)
    assert len(tools) == 8


def test_db_tools_count(db, session_id, mock_kalshi, mock_polymarket):
    tools = create_db_tools(db, session_id, mock_kalshi, mock_polymarket)
    assert len(tools) == 1
