"""Tests for finance_agent.kalshi_client -- Kalshi SDK wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import pytest

from finance_agent.config import TradingConfig
from finance_agent.kalshi_client import KalshiAPIClient, _optional

# ── _optional helper ─────────────────────────────────────────────


def test_optional_filters_none():
    assert _optional(a=1, b=None, c="x") == {"a": 1, "c": "x"}


def test_optional_all_none():
    assert _optional(a=None, b=None) == {}


def test_optional_empty():
    assert _optional() == {}


# ── Client fixture ───────────────────────────────────────────────


@pytest.fixture
def kalshi_client(monkeypatch):
    """KalshiAPIClient with mocked SDK and key file."""
    for key in list(TradingConfig.model_fields):
        monkeypatch.delenv(key.upper(), raising=False)
        monkeypatch.delenv(key, raising=False)

    config = TradingConfig(
        kalshi_api_key_id="test-key",
        kalshi_private_key_path="/fake/key.pem",
    )
    with (
        patch("finance_agent.kalshi_client.KalshiClient") as mock_sdk,
        patch("builtins.open", mock_open(read_data="FAKE_PEM_KEY")),
    ):
        client = KalshiAPIClient(config)
        client._client = mock_sdk.return_value
        yield client


# ── Rate limiting ────────────────────────────────────────────────


def test_search_markets_calls_rate_read(kalshi_client):
    kalshi_client._client.get_markets.return_value = MagicMock()
    with patch.object(kalshi_client, "_rate_read") as mock_rate:
        kalshi_client.search_markets()
        mock_rate.assert_called_once()


def test_create_order_calls_rate_write(kalshi_client):
    kalshi_client._client.create_order.return_value = MagicMock()
    with patch.object(kalshi_client, "_rate_write") as mock_rate:
        with patch("finance_agent.kalshi_client.CreateOrderRequest"):
            kalshi_client.create_order(ticker="T-1", action="buy", side="yes", count=1)
        mock_rate.assert_called_once()


# ── Argument forwarding ──────────────────────────────────────────


def test_get_market_passes_ticker(kalshi_client):
    kalshi_client._client.get_market.return_value = MagicMock()
    kalshi_client.get_market("TICKER-1")
    kalshi_client._client.get_market.assert_called_once_with("TICKER-1")


def test_get_orderbook_passes_depth(kalshi_client):
    kalshi_client._client.get_market_orderbook.return_value = MagicMock()
    kalshi_client.get_orderbook("TICKER-1", depth=5)
    kalshi_client._client.get_market_orderbook.assert_called_once_with("TICKER-1", depth=5)


def test_get_event_passes_ticker(kalshi_client):
    kalshi_client._client.get_event.return_value = MagicMock()
    kalshi_client.get_event("EVT-1")
    kalshi_client._client.get_event.assert_called_once_with("EVT-1", with_nested_markets=True)


def test_get_events_forwards_cursor(kalshi_client):
    kalshi_client._client.get_events.return_value = MagicMock()
    kalshi_client.get_events(status="open", cursor="abc123")
    call_kwargs = kalshi_client._client.get_events.call_args[1]
    assert call_kwargs["cursor"] == "abc123"


# ── Response conversion ──────────────────────────────────────────


def test_to_dict_with_to_dict_method(kalshi_client):
    mock_resp = MagicMock()
    mock_resp.to_dict.return_value = {"key": "val"}
    result = kalshi_client._to_dict(mock_resp)
    assert result == {"key": "val"}


def test_get_balance_returns_dict(kalshi_client):
    mock_resp = MagicMock()
    mock_resp.to_dict.return_value = {"balance": 1000}
    kalshi_client._client.get_balance.return_value = mock_resp
    result = kalshi_client.get_balance()
    assert result == {"balance": 1000}
