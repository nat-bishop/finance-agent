"""Shared fixtures for finance-agent tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from finance_agent.database import AgentDatabase

# ── Core DB fixture ──────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Fresh AgentDatabase with Alembic migrations applied (temp file-based SQLite)."""
    db_path = tmp_path / "test_agent.db"
    database = AgentDatabase(str(db_path))
    yield database
    database.close()


@pytest.fixture
def session_id(db):
    """Create a test session and return its ID."""
    return db.create_session()


# ── Sample data factories ────────────────────────────────────────


def _recent_iso(hours_ago: float = 0) -> str:
    """Return an ISO timestamp `hours_ago` hours in the past."""
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture
def sample_market_snapshot():
    """Factory for market snapshot dicts matching insert_market_snapshots schema."""

    def _make(
        ticker="TICKER-A",
        exchange="kalshi",
        status="open",
        yes_bid=45,
        yes_ask=55,
        mid_price_cents=50,
        spread_cents=10,
        volume=1000,
        volume_24h=500,
        category="Politics",
        event_ticker="EVT-1",
        days_to_expiration=5.0,
        settlement_value=None,
        captured_at=None,
        **overrides,
    ):
        base = {
            "captured_at": captured_at or _recent_iso(),
            "source": "collector",
            "exchange": exchange,
            "ticker": ticker,
            "event_ticker": event_ticker,
            "series_ticker": None,
            "title": f"Test Market {ticker}",
            "category": category,
            "status": status,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": None,
            "no_ask": None,
            "last_price": mid_price_cents,
            "volume": volume,
            "volume_24h": volume_24h,
            "open_interest": 200,
            "spread_cents": spread_cents,
            "mid_price_cents": mid_price_cents,
            "implied_probability": mid_price_cents / 100.0 if mid_price_cents else None,
            "days_to_expiration": days_to_expiration,
            "close_time": "2026-03-01T00:00:00+00:00",
            "settlement_value": settlement_value,
            "markets_in_event": None,
            "raw_json": "{}",
        }
        base.update(overrides)
        return base

    return _make


@pytest.fixture
def sample_event():
    """Factory for event dicts matching upsert_event params."""

    def _make(
        event_ticker="EVT-1",
        exchange="kalshi",
        title="Test Event",
        category="Politics",
        mutually_exclusive=True,
        markets=None,
    ):
        if markets is None:
            markets = [
                {
                    "ticker": "MKT-A",
                    "title": "Yes A",
                    "yes_bid": 45,
                    "yes_ask": 55,
                    "status": "open",
                },
                {
                    "ticker": "MKT-B",
                    "title": "Yes B",
                    "yes_bid": 40,
                    "yes_ask": 50,
                    "status": "open",
                },
            ]
        return {
            "event_ticker": event_ticker,
            "exchange": exchange,
            "title": title,
            "category": category,
            "mutually_exclusive": mutually_exclusive,
            "markets_json": json.dumps(markets),
        }

    return _make


@pytest.fixture
def sample_signal():
    """Factory for signal dicts matching insert_signals schema."""

    def _make(scan_type="wide_spread", ticker="TICKER-A", strength=0.5, edge=5.0, **extra):
        return {
            "scan_type": scan_type,
            "ticker": ticker,
            "signal_strength": strength,
            "estimated_edge_pct": edge,
            "details_json": {"test": True},
            **extra,
        }

    return _make


# ── Mock API clients ─────────────────────────────────────────────


@pytest.fixture
def mock_kalshi():
    """Mock KalshiAPIClient with realistic return values."""
    client = MagicMock()
    client.search_markets.return_value = {
        "markets": [
            {
                "ticker": "K-MKT-1",
                "title": "Test Kalshi Market",
                "yes_bid": 45,
                "yes_ask": 55,
                "status": "open",
            },
        ],
        "cursor": None,
    }
    client.get_market.return_value = {"ticker": "K-MKT-1", "title": "Test Kalshi Market"}
    client.get_orderbook.return_value = {"yes": [[45, 100]], "no": [[55, 100]]}
    client.get_event.return_value = {"event_ticker": "EVT-1", "title": "Test Event", "markets": []}
    client.get_candlesticks.return_value = {"candlesticks": []}
    client.get_trades.return_value = {"trades": []}
    client.get_balance.return_value = {"balance": 10000}
    client.get_positions.return_value = {"positions": []}
    client.get_fills.return_value = {"fills": []}
    client.get_settlements.return_value = {"settlements": []}
    client.get_orders.return_value = {"orders": []}
    client.get_events.return_value = {"events": [], "cursor": None}
    return client


@pytest.fixture
def mock_polymarket():
    """Mock PolymarketAPIClient with realistic return values."""
    client = MagicMock()
    client.search_markets.return_value = {
        "markets": [
            {"slug": "test-market", "title": "Test PM Market", "yes_price": 0.52, "active": True},
        ],
    }
    client.get_market.return_value = {"slug": "test-market", "title": "Test PM Market"}
    client.get_orderbook.return_value = {"bids": [], "asks": []}
    client.get_bbo.return_value = {"best_bid": 0.50, "best_ask": 0.54}
    client.get_event.return_value = {"slug": "test-event", "title": "Test Event", "markets": []}
    client.get_trades.return_value = {"trades": []}
    client.get_balance.return_value = {"balance": "500.00"}
    client.get_positions.return_value = {"positions": []}
    client.get_orders.return_value = {"orders": []}
    client.list_events.return_value = {"events": []}
    return client
