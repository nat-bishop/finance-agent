"""Tests for finance_agent.polymarket_client -- Polymarket US SDK wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
    "cents,expected",
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
    with patch("finance_agent.polymarket_client.PolymarketUS") as mock_sdk:
        client = PolymarketAPIClient(credentials, config)
        client._client = mock_sdk.return_value
        yield client


# ── Client methods ───────────────────────────────────────────────


def test_search_markets_status_active(pm_client):
    pm_client._client.markets.list.return_value = MagicMock()
    pm_client.search_markets(query="test", status="open", limit=25)
    call_args = pm_client._client.markets.list.call_args[0][0]
    assert call_args["active"] is True
    assert call_args["query"] == "test"
    assert call_args["limit"] == 25


def test_search_markets_status_closed(pm_client):
    pm_client._client.markets.list.return_value = MagicMock()
    pm_client.search_markets(status="closed")
    call_args = pm_client._client.markets.list.call_args[0][0]
    assert call_args["active"] is False


def test_get_market_by_slug(pm_client):
    pm_client._client.markets.retrieve_by_slug.return_value = MagicMock()
    pm_client.get_market("test-slug")
    pm_client._client.markets.retrieve_by_slug.assert_called_once_with("test-slug")


def test_cancel_order_returns_manual_dict(pm_client):
    pm_client._client.orders.cancel.return_value = None
    result = pm_client.cancel_order("order-123")
    assert result == {"status": "cancelled", "order_id": "order-123"}


def test_create_order_passes_intent(pm_client):
    pm_client._client.orders.create.return_value = MagicMock()
    pm_client.create_order(slug="test", intent="ORDER_INTENT_BUY_LONG", price="0.50")
    call_args = pm_client._client.orders.create.call_args[0][0]
    assert call_args["intent"] == "ORDER_INTENT_BUY_LONG"
    assert call_args["marketSlug"] == "test"
    assert call_args["price"] == {"value": "0.50", "currency": "USD"}


def test_list_events_passes_offset(pm_client):
    pm_client._client.events.list.return_value = MagicMock()
    pm_client.list_events(active=True, limit=50, offset=100)
    call_args = pm_client._client.events.list.call_args[0][0]
    assert call_args["offset"] == 100


def test_get_orders_with_filter(pm_client):
    pm_client._client.orders.list.return_value = MagicMock()
    pm_client.get_orders(market_slug="test-slug", status="resting")
    call_args = pm_client._client.orders.list.call_args[0][0]
    assert call_args["marketSlug"] == "test-slug"
    assert call_args["status"] == "resting"
