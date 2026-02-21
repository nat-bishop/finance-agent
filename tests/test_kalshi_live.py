"""Live integration tests for Kalshi API via kalshi_python_async SDK.

Run with: make test-live
Requires: .env with KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY set.
Skipped by default in `make test` via the `live` marker.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from finance_agent.config import load_configs  # noqa: E402
from finance_agent.fees import best_price_and_depth  # noqa: E402
from finance_agent.kalshi_client import KalshiAPIClient  # noqa: E402

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client() -> KalshiAPIClient:
    """Single authenticated client reused across all tests."""
    _, creds, tc = load_configs()
    return KalshiAPIClient(creds, tc)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def liquid_ticker(client: KalshiAPIClient) -> str:
    """Find a market with open interest for orderbook tests."""
    resp = await client.get_events(status="open", limit=20, with_nested_markets=True)
    for event in resp.get("events", []):
        for mkt in event.get("markets", []):
            oi = mkt.get("open_interest", 0) or 0
            vol = mkt.get("volume", 0) or 0
            if oi > 0 or vol > 500:
                return mkt["ticker"]
    # Fallback: just use the first open market
    markets = await client.search_markets(status="open", limit=1)
    return markets["markets"][0]["ticker"]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def empty_ticker(client: KalshiAPIClient) -> str:
    """Find a market with zero volume (likely empty orderbook)."""
    resp = await client.search_markets(status="open", limit=20)
    for mkt in resp.get("markets", []):
        vol = mkt.get("volume", 0) or 0
        oi = mkt.get("open_interest", 0) or 0
        if vol == 0 and oi == 0:
            return mkt["ticker"]
    return resp["markets"][0]["ticker"]


# ── Exchange ───────────────────────────────────────────────────────


async def test_get_exchange_status(client: KalshiAPIClient):
    resp = await client.get_exchange_status()
    assert isinstance(resp, dict)


# ── Markets ────────────────────────────────────────────────────────


async def test_search_markets(client: KalshiAPIClient):
    resp = await client.search_markets(status="open", limit=5)
    assert "markets" in resp
    assert "cursor" in resp
    assert len(resp["markets"]) > 0
    mkt = resp["markets"][0]
    assert "ticker" in mkt


async def test_get_market(client: KalshiAPIClient, liquid_ticker: str):
    resp = await client.get_market(liquid_ticker)
    assert isinstance(resp, dict)
    # Response may be {"market": {...}} or flat
    inner = resp.get("market", resp)
    assert "ticker" in inner


async def test_get_orderbook_liquid(client: KalshiAPIClient, liquid_ticker: str):
    ob = await client.get_orderbook(liquid_ticker, depth=5)
    assert isinstance(ob, dict)
    # Should have orderbook key
    inner = ob.get("orderbook", ob)
    # At least one side should have data
    has_data = any(
        inner.get(k) for k in ("yes", "no", "true", "false", "yes_dollars", "no_dollars")
    )
    if has_data:
        yes_price, yes_depth = best_price_and_depth(ob, "yes")
        no_price, no_depth = best_price_and_depth(ob, "no")
        # At least one side should parse successfully
        assert yes_price is not None or no_price is not None
        if yes_price is not None:
            assert 1 <= yes_price <= 99
            assert yes_depth > 0
        if no_price is not None:
            assert 1 <= no_price <= 99
            assert no_depth > 0


async def test_get_orderbook_empty(client: KalshiAPIClient, empty_ticker: str):
    """Empty orderbook should not crash — returns (None, 0)."""
    ob = await client.get_orderbook(empty_ticker, depth=5)
    assert isinstance(ob, dict)
    yes_price, _yes_depth = best_price_and_depth(ob, "yes")
    no_price, _no_depth = best_price_and_depth(ob, "no")
    # Both None is fine (empty), or populated is fine (market got orders since fixture)
    assert yes_price is None or (1 <= yes_price <= 99)
    assert no_price is None or (1 <= no_price <= 99)


# ── Events ─────────────────────────────────────────────────────────


async def test_get_events(client: KalshiAPIClient):
    resp = await client.get_events(status="open", limit=5, with_nested_markets=True)
    assert "events" in resp
    assert len(resp["events"]) > 0
    event = resp["events"][0]
    assert "event_ticker" in event


async def test_get_event(client: KalshiAPIClient):
    # First get an event ticker
    events_resp = await client.get_events(status="open", limit=1, with_nested_markets=False)
    event_ticker = events_resp["events"][0]["event_ticker"]
    resp = await client.get_event(event_ticker)
    assert isinstance(resp, dict)
    inner = resp.get("event", resp)
    assert "event_ticker" in inner


# ── Trades ─────────────────────────────────────────────────────────


async def test_get_trades(client: KalshiAPIClient, liquid_ticker: str):
    resp = await client.get_trades(liquid_ticker, limit=5)
    assert "trades" in resp
    assert isinstance(resp["trades"], list)


# ── Candlesticks ───────────────────────────────────────────────────


async def test_get_candlesticks(client: KalshiAPIClient, liquid_ticker: str):
    resp = await client.get_candlesticks(liquid_ticker, period_interval=60)
    assert isinstance(resp, dict)


# ── Portfolio ──────────────────────────────────────────────────────


async def test_get_balance(client: KalshiAPIClient):
    resp = await client.get_balance()
    assert isinstance(resp, dict)


async def test_get_positions(client: KalshiAPIClient):
    resp = await client.get_positions(limit=5)
    assert isinstance(resp, dict)


async def test_get_fills(client: KalshiAPIClient):
    resp = await client.get_fills(limit=5)
    assert isinstance(resp, dict)


async def test_get_settlements(client: KalshiAPIClient):
    resp = await client.get_settlements(limit=5)
    assert isinstance(resp, dict)


# ── Orders ─────────────────────────────────────────────────────────


async def test_get_orders(client: KalshiAPIClient):
    resp = await client.get_orders(limit=5)
    assert isinstance(resp, dict)
