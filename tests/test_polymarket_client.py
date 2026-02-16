"""Tests for finance_agent.polymarket_client -- Polymarket US SDK wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from finance_agent.config import Credentials, TradingConfig
from finance_agent.polymarket_client import (
    PM_INTENT_MAP,
    PM_INTENT_REVERSE,
    PolymarketAPIClient,
    cents_to_usd,
)

# ── Module-level constants ───────────────────────────────────────


def test_pm_intent_map_completeness():
    assert len(PM_INTENT_MAP) == 4
    assert ("buy", "yes") in PM_INTENT_MAP
    assert ("sell", "yes") in PM_INTENT_MAP
    assert ("buy", "no") in PM_INTENT_MAP
    assert ("sell", "no") in PM_INTENT_MAP


def test_pm_intent_reverse_roundtrip():
    for key, val in PM_INTENT_MAP.items():
        assert PM_INTENT_REVERSE[val] == key


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(50, "0.50"), (1, "0.01"), (99, "0.99"), (0, "0.00"), (100, "1.00")],
)
def test_cents_to_usd(cents, expected):
    assert cents_to_usd(cents) == expected


# ── Client fixture ───────────────────────────────────────────────


@pytest.fixture
def pm_client(monkeypatch):
    for key in Credentials.model_fields:
        monkeypatch.setenv(key.upper(), "")

    credentials = Credentials(
        polymarket_key_id="test-key",
        polymarket_secret_key="test-secret",
    )
    config = TradingConfig(polymarket_enabled=True)
    with patch("finance_agent.polymarket_client.AsyncPolymarketUS") as mock_sdk:
        client = PolymarketAPIClient(credentials, config)
        # Set up async mocks for nested SDK resources
        mock_instance = mock_sdk.return_value
        mock_instance.markets.list = AsyncMock(return_value=MagicMock())
        mock_instance.markets.retrieve_by_slug = AsyncMock(return_value=MagicMock())
        mock_instance.markets.book = AsyncMock(return_value=MagicMock())
        mock_instance.markets.bbo = AsyncMock(return_value=MagicMock())
        mock_instance.markets.trades = AsyncMock(return_value=MagicMock())
        mock_instance.events.retrieve_by_slug = AsyncMock(return_value=MagicMock())
        mock_instance.events.list = AsyncMock(return_value=MagicMock())
        mock_instance.account.balances = AsyncMock(return_value=MagicMock())
        mock_instance.portfolio.positions = AsyncMock(return_value=MagicMock())
        mock_instance.orders.list = AsyncMock(return_value=MagicMock())
        mock_instance.orders.create = AsyncMock(return_value=MagicMock())
        mock_instance.orders.cancel = AsyncMock(return_value=None)
        mock_instance.close = AsyncMock()
        client._client = mock_instance
        yield client


# ── Client methods ───────────────────────────────────────────────


async def test_search_markets_status_active(pm_client):
    await pm_client.search_markets(query="test", status="open", limit=25)
    call_args = pm_client._client.markets.list.call_args[0][0]
    assert call_args["active"] is True
    assert call_args["query"] == "test"
    assert call_args["limit"] == 25


async def test_search_markets_status_closed(pm_client):
    await pm_client.search_markets(status="closed")
    call_args = pm_client._client.markets.list.call_args[0][0]
    assert call_args["active"] is False


async def test_get_market_by_slug(pm_client):
    await pm_client.get_market("test-slug")
    pm_client._client.markets.retrieve_by_slug.assert_awaited_once_with("test-slug")


async def test_cancel_order_returns_manual_dict(pm_client):
    result = await pm_client.cancel_order("order-123")
    assert result == {"status": "cancelled", "order_id": "order-123"}


async def test_create_order_passes_intent(pm_client):
    await pm_client.create_order(slug="test", intent="ORDER_INTENT_BUY_LONG", price="0.50")
    call_args = pm_client._client.orders.create.call_args[0][0]
    assert call_args["intent"] == "ORDER_INTENT_BUY_LONG"
    assert call_args["marketSlug"] == "test"
    assert call_args["price"] == {"value": "0.50", "currency": "USD"}


async def test_list_events_passes_offset(pm_client):
    await pm_client.list_events(active=True, limit=50, offset=100)
    call_args = pm_client._client.events.list.call_args[0][0]
    assert call_args["offset"] == 100


async def test_get_orders_with_filter(pm_client):
    await pm_client.get_orders(market_slug="test-slug", status="resting")
    call_args = pm_client._client.orders.list.call_args[0][0]
    assert call_args["marketSlug"] == "test-slug"
    assert call_args["status"] == "resting"
