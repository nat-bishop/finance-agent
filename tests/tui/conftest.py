"""TUI test fixtures -- builds on root conftest.py fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from finance_agent.config import TradingConfig
from finance_agent.tui.services import TUIServices


@pytest.fixture
def trading_config(tmp_path) -> TradingConfig:
    """TradingConfig with safe test defaults (edge validation disabled)."""
    return TradingConfig(
        kalshi_max_position_usd=100.0,
        recommendation_ttl_minutes=60,
        db_path=str(tmp_path / "test.db"),
        min_edge_pct=0.0,
    )


def _mock_fill_monitor() -> MagicMock:
    """Create a mock FillMonitor that instantly reports fills."""
    monitor = MagicMock()
    monitor.wait_for_fill = AsyncMock(return_value={"fill_price_cents": 45, "fill_quantity": 10})
    monitor.close = AsyncMock()
    return monitor


@pytest.fixture
def services(db, mock_kalshi, trading_config, session_id) -> TUIServices:
    """TUIServices wired to real DB + mock Kalshi client + mock fill monitor."""
    svc = TUIServices(
        db=db,
        kalshi=mock_kalshi,
        config=trading_config,
        session_id=session_id,
    )
    svc._fill_monitor = _mock_fill_monitor()
    return svc


@pytest.fixture
def sample_group() -> dict:
    """A minimal recommendation group dict for testing."""
    return {
        "id": 1,
        "session_id": "test1234",
        "status": "pending",
        "thesis": "Test bracket arb opportunity",
        "equivalence_notes": "Same event, mutually exclusive outcomes",
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
                "market_title": "Test Market A",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
                "order_type": "limit",
                "status": "pending",
                "order_id": None,
                "executed_at": None,
            },
            {
                "id": 2,
                "group_id": 1,
                "leg_index": 1,
                "exchange": "kalshi",
                "market_id": "K-MKT-2",
                "market_title": "Test Market B",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
                "order_type": "limit",
                "status": "pending",
                "order_id": None,
                "executed_at": None,
            },
            {
                "id": 3,
                "group_id": 1,
                "leg_index": 2,
                "exchange": "kalshi",
                "market_id": "K-MKT-3",
                "market_title": "Test Market C",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
                "order_type": "limit",
                "status": "pending",
                "order_id": None,
                "executed_at": None,
            },
        ],
    }
