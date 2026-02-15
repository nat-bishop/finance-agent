"""TUI test fixtures -- builds on root conftest.py fixtures."""

from __future__ import annotations

import pytest

from finance_agent.config import TradingConfig
from finance_agent.tui.services import TUIServices


@pytest.fixture
def trading_config(tmp_path) -> TradingConfig:
    """TradingConfig with safe test defaults."""
    return TradingConfig(
        kalshi_max_position_usd=100.0,
        polymarket_max_position_usd=50.0,
        recommendation_ttl_minutes=60,
        db_path=str(tmp_path / "test.db"),
    )


@pytest.fixture
def services(db, mock_kalshi, mock_polymarket, trading_config, session_id) -> TUIServices:
    """TUIServices wired to real DB + mock exchange clients."""
    return TUIServices(
        db=db,
        kalshi=mock_kalshi,
        polymarket=mock_polymarket,
        config=trading_config,
        session_id=session_id,
    )


@pytest.fixture
def services_no_pm(db, mock_kalshi, trading_config, session_id) -> TUIServices:
    """TUIServices with Polymarket disabled (None)."""
    return TUIServices(
        db=db,
        kalshi=mock_kalshi,
        polymarket=None,
        config=trading_config,
        session_id=session_id,
    )


@pytest.fixture
def sample_group() -> dict:
    """A minimal recommendation group dict for testing."""
    return {
        "id": 1,
        "session_id": "test1234",
        "status": "pending",
        "thesis": "Test arb opportunity",
        "equivalence_notes": "Same settlement source",
        "estimated_edge_pct": 7.5,
        "expires_at": "2027-12-31T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
        "legs": [
            {
                "id": 1,
                "group_id": 1,
                "leg_index": 0,
                "exchange": "kalshi",
                "market_id": "K-MKT-1",
                "market_title": "Test Market Kalshi",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
                "order_type": "limit",
                "status": "pending",
                "order_id": None,
                "executed_at": None,
            },
            {
                "id": 2,
                "group_id": 1,
                "leg_index": 1,
                "exchange": "polymarket",
                "market_id": "PM-MKT-1",
                "market_title": "Test Market PM",
                "action": "sell",
                "side": "yes",
                "quantity": 10,
                "price_cents": 52,
                "order_type": "limit",
                "status": "pending",
                "order_id": None,
                "executed_at": None,
            },
        ],
    }
