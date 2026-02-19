"""Tests for finance_agent.collector -- data collection pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from finance_agent.collector import (
    _as_list,
    _compute_derived,
    _generate_markets_jsonl,
    _parse_days_to_expiry,
    collect_kalshi,
    resolve_settlements,
)

# ── _parse_days_to_expiry ────────────────────────────────────────


def test_parse_days_none():
    assert _parse_days_to_expiry(None) is None


def test_parse_days_empty_string():
    assert _parse_days_to_expiry("") is None


def test_parse_days_iso_string():
    future = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    result = _parse_days_to_expiry(future)
    assert result is not None
    assert 4.9 < result < 5.1


def test_parse_days_z_suffix():
    future = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = _parse_days_to_expiry(future)
    assert result is not None
    assert 1.9 < result < 2.1


def test_parse_days_unix_timestamp():
    future_ts = (datetime.now(UTC) + timedelta(days=3)).timestamp()
    result = _parse_days_to_expiry(future_ts)
    assert result is not None
    assert 2.9 < result < 3.1


def test_parse_days_datetime_object():
    """datetime objects (as returned by Kalshi SDK) are parsed correctly."""
    future = datetime.now(UTC) + timedelta(days=5)
    result = _parse_days_to_expiry(future)
    assert result is not None
    assert 4.9 < result < 5.1


def test_parse_days_naive_datetime():
    """Naive datetime objects get UTC timezone applied."""
    future = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3)
    result = _parse_days_to_expiry(future)
    assert result is not None
    assert 2.9 < result < 3.1


def test_parse_days_past_date():
    past = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    result = _parse_days_to_expiry(past)
    assert result == 0.0


def test_parse_days_invalid_string():
    assert _parse_days_to_expiry("not-a-date") is None


@pytest.mark.parametrize("bad_input", [[], {}, object()])
def test_parse_days_non_parseable(bad_input):
    assert _parse_days_to_expiry(bad_input) is None


# ── _compute_derived (Kalshi) ────────────────────────────────────


def test_compute_derived_full_data():
    now = datetime.now(UTC).isoformat()
    market = {
        "ticker": "K-MKT-1",
        "event_ticker": "EVT-1",
        "series_ticker": "SER-1",
        "title": "Test Market",
        "category": "Politics",
        "status": "open",
        "yes_bid": 45,
        "yes_ask": 55,
        "no_bid": 45,
        "no_ask": 55,
        "last_price": 50,
        "volume": 1000,
        "volume_24h": 500,
        "open_interest": 200,
        "close_time": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        "settlement_value": None,
    }
    result = _compute_derived(market, now)
    assert result["spread_cents"] == 10
    assert result["mid_price_cents"] == 50
    assert result["implied_probability"] == 0.5
    assert result["exchange"] == "kalshi"


def test_compute_derived_missing_bid():
    now = datetime.now(UTC).isoformat()
    market = {"yes_bid": 0, "yes_ask": 55, "ticker": "K-1"}
    result = _compute_derived(market, now)
    assert result["spread_cents"] is None
    assert result["mid_price_cents"] is None


def test_compute_derived_settlement_value():
    now = datetime.now(UTC).isoformat()
    market = {"ticker": "K-1", "yes_bid": 45, "yes_ask": 55, "settlement_value": "yes"}
    result = _compute_derived(market, now)
    assert result["settlement_value"] == "yes"


# ── _as_list ─────────────────────────────────────────────────────


def test_as_list_list_input():
    assert _as_list([1, 2, 3]) == [1, 2, 3]


def test_as_list_dict_with_key():
    assert _as_list({"markets": [1, 2]}, "markets") == [1, 2]


def test_as_list_fallback_key():
    assert _as_list({"data": [1]}, "markets", "data") == [1]


def test_as_list_no_matching_key():
    assert _as_list({"other": [1]}, "markets") == []


# ── collect_kalshi (events-first, async) ─────────────────────────


async def test_collect_kalshi_pagination(db, mock_kalshi):
    """Events with nested markets are collected in a single pass."""
    mock_kalshi.get_events = AsyncMock(
        side_effect=[
            {
                "events": [
                    {
                        "event_ticker": "EVT-1",
                        "title": "Event 1",
                        "category": "Politics",
                        "mutually_exclusive": True,
                        "markets": [
                            {
                                "ticker": f"M-{i}",
                                "title": f"Market {i}",
                                "yes_bid": 45,
                                "yes_ask": 55,
                                "status": "open",
                            }
                            for i in range(3)
                        ],
                    },
                ],
                "cursor": "page2",
            },
            {
                "events": [
                    {
                        "event_ticker": "EVT-2",
                        "title": "Event 2",
                        "category": "Sports",
                        "markets": [
                            {
                                "ticker": "M-3",
                                "title": "Market 3",
                                "yes_bid": 40,
                                "yes_ask": 60,
                                "status": "open",
                            },
                        ],
                    },
                ],
                "cursor": None,
            },
        ]
    )
    event_count, market_count = await collect_kalshi(mock_kalshi, db, status="open")
    assert event_count == 2
    assert market_count == 4
    assert mock_kalshi.get_events.call_count == 2

    events = db.get_all_events()
    tickers = {e["event_ticker"] for e in events}
    assert "EVT-1" in tickers
    assert "EVT-2" in tickers


async def test_collect_kalshi_max_pages(db, mock_kalshi):
    """max_pages limits how many pages are fetched."""
    mock_kalshi.get_events = AsyncMock(
        return_value={
            "events": [
                {
                    "event_ticker": "EVT-1",
                    "title": "Event",
                    "markets": [
                        {"ticker": "M-1", "yes_bid": 45, "yes_ask": 55, "status": "open"},
                    ],
                },
            ],
            "cursor": "more",
        }
    )
    event_count, market_count = await collect_kalshi(
        mock_kalshi, db, status="settled", max_pages=1
    )
    assert event_count == 1
    assert market_count == 1
    assert mock_kalshi.get_events.call_count == 1


# ── _generate_markets_jsonl ─────────────────────────────────────


def test_generate_markets_jsonl(db, sample_market_snapshot, tmp_path):
    # Insert an event so the event-join path is exercised
    db.upsert_event(
        event_ticker="EVT-1",
        exchange="kalshi",
        title="Test Event Title",
        category="Politics",
        mutually_exclusive=True,
        markets_json="[]",
    )

    # Kalshi market with raw_json containing rules_primary
    kalshi_raw = json.dumps({"rules_primary": "Resolves Yes if X happens."})
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                ticker="K-1",
                exchange="kalshi",
                category="Politics",
                mid_price_cents=50,
                raw_json=kalshi_raw,
            ),
        ]
    )
    output = tmp_path / "markets.jsonl"
    _generate_markets_jsonl(db, str(output))

    lines = output.read_text().strip().split("\n")
    assert len(lines) == 1

    records = [json.loads(line) for line in lines]
    assert records[0]["ticker"] == "K-1"

    # Verify all expected fields are present
    for r in records:
        assert "exchange" in r
        assert "ticker" in r
        assert "title" in r
        assert "mid_price_cents" in r
        assert "category" in r
        assert "event_title" in r
        assert "mutually_exclusive" in r
        assert "description" in r

    # Verify Kalshi record with matching event
    kalshi_rec = records[0]
    assert kalshi_rec["exchange"] == "kalshi"
    assert kalshi_rec["mid_price_cents"] == 50
    assert kalshi_rec["category"] == "Politics"
    assert kalshi_rec["event_title"] == "Test Event Title"
    assert kalshi_rec["mutually_exclusive"] is True
    assert kalshi_rec["description"] == "Resolves Yes if X happens."


# ── resolve_settlements ─────────────────────────────────────────


async def test_resolve_settlements_settles_leg(db, session_id, mock_kalshi):
    """Settled market updates recommendation leg."""
    db.log_recommendation_group(
        session_id=session_id,
        thesis="Test bracket",
        estimated_edge_pct=8.0,
        strategy="bracket",
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-SETTLED",
                "market_title": "Test",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-PENDING",
                "market_title": "Test 2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 50,
            },
        ],
    )

    async def mock_get_market(ticker):
        if ticker == "K-SETTLED":
            return {"market": {"ticker": ticker, "settlement_value": 100}}
        return {"market": {"ticker": ticker}}

    mock_kalshi.get_market = AsyncMock(side_effect=mock_get_market)

    count = await resolve_settlements(mock_kalshi, db)
    assert count == 1  # Only K-SETTLED resolved


async def test_resolve_settlements_computes_pnl(db, session_id, mock_kalshi):
    """When all legs settle, P&L is computed automatically."""
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test bracket",
        estimated_edge_pct=8.0,
        strategy="bracket",
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Leg 1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "market_title": "Leg 2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-3",
                "market_title": "Leg 3",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
        ],
    )

    async def mock_get_market(ticker):
        return {"market": {"ticker": ticker, "settlement_value": 100}}

    mock_kalshi.get_market = AsyncMock(side_effect=mock_get_market)

    await resolve_settlements(mock_kalshi, db)

    group = db.get_group(group_id)
    assert group["hypothetical_pnl_usd"] is not None
    assert group["hypothetical_pnl_usd"] > 0  # 90c cost for 100c payout


async def test_resolve_settlements_handles_404(db, session_id, mock_kalshi):
    """Markets that error are skipped gracefully."""
    db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-GONE",
                "market_title": "Delisted",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
        ],
    )
    mock_kalshi.get_market = AsyncMock(side_effect=Exception("404 Not Found"))

    count = await resolve_settlements(mock_kalshi, db)
    assert count == 0  # No legs settled

    tickers = db.get_unresolved_leg_tickers()
    assert "K-GONE" in tickers  # Still unresolved


async def test_resolve_settlements_no_tickers(db, mock_kalshi):
    """No unresolved tickers → no API calls."""
    count = await resolve_settlements(mock_kalshi, db)
    assert count == 0
    mock_kalshi.get_market.assert_not_called()
