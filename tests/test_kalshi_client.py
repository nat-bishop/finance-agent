"""Tests for finance_agent.kalshi_client -- Kalshi SDK wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from finance_agent.config import Credentials, TradingConfig
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
    for key in Credentials.model_fields:
        monkeypatch.setenv(key.upper(), "")

    credentials = Credentials(
        kalshi_api_key_id="test-key",
        kalshi_private_key_path="/fake/key.pem",
    )
    config = TradingConfig()
    with (
        patch("finance_agent.kalshi_client.KalshiClient") as mock_sdk,
        patch("pathlib.Path.open", mock_open(read_data="FAKE_PEM_KEY")),
    ):
        client = KalshiAPIClient(credentials, config)
        # Replace SDK methods with AsyncMocks
        mock_instance = mock_sdk.return_value
        mock_instance.get_markets = AsyncMock(return_value=MagicMock())
        mock_instance.get_market = AsyncMock(return_value=MagicMock())
        mock_instance.get_market_orderbook = AsyncMock(return_value=MagicMock())
        mock_instance.get_event = AsyncMock(return_value=MagicMock())
        mock_instance.get_trades = AsyncMock(return_value=MagicMock())
        mock_instance.get_balance = AsyncMock(return_value=MagicMock())
        mock_instance.get_positions = AsyncMock(return_value=MagicMock())
        mock_instance.get_fills = AsyncMock(return_value=MagicMock())
        mock_instance.get_settlements = AsyncMock(return_value=MagicMock())
        mock_instance.get_orders = AsyncMock(return_value=MagicMock())
        mock_instance.get_events = AsyncMock(return_value=MagicMock())
        mock_instance.create_order = AsyncMock(return_value=MagicMock())
        mock_instance.cancel_order = AsyncMock(return_value=MagicMock())
        mock_instance.get_exchange_status = AsyncMock(return_value=MagicMock())
        mock_instance.batch_get_market_candlesticks = AsyncMock(return_value=MagicMock())
        client._client = mock_instance
        yield client


# ── Rate limiting ────────────────────────────────────────────────


async def test_search_markets_calls_rate_read(kalshi_client):
    with patch.object(kalshi_client, "_rate_read", new_callable=AsyncMock) as mock_rate:
        await kalshi_client.search_markets()
        mock_rate.assert_awaited_once()


async def test_create_order_calls_rate_write(kalshi_client):
    with patch.object(kalshi_client, "_rate_write", new_callable=AsyncMock) as mock_rate:
        await kalshi_client.create_order(ticker="T-1", action="buy", side="yes", count=1)
        mock_rate.assert_awaited_once()


# ── Argument forwarding ──────────────────────────────────────────


async def test_get_market_passes_ticker(kalshi_client):
    await kalshi_client.get_market("TICKER-1")
    kalshi_client._client.get_market.assert_awaited_once_with("TICKER-1")


async def test_get_orderbook_passes_depth(kalshi_client):
    await kalshi_client.get_orderbook("TICKER-1", depth=5)
    kalshi_client._client.get_market_orderbook.assert_awaited_once_with("TICKER-1", depth=5)


async def test_get_events_forwards_cursor(kalshi_client):
    await kalshi_client.get_events(status="open", cursor="abc123")
    call_kwargs = kalshi_client._client.get_events.call_args[1]
    assert call_kwargs["cursor"] == "abc123"


# ── Response conversion ──────────────────────────────────────────


def test_to_dict_with_to_dict_method(kalshi_client):
    mock_resp = MagicMock()
    mock_resp.to_dict.return_value = {"key": "val"}
    result = kalshi_client._to_dict(mock_resp)
    assert result == {"key": "val"}


async def test_get_balance_returns_dict(kalshi_client):
    mock_resp = MagicMock()
    mock_resp.to_dict.return_value = {"balance": 1000}
    kalshi_client._client.get_balance = AsyncMock(return_value=mock_resp)
    result = await kalshi_client.get_balance()
    assert result == {"balance": 1000}
