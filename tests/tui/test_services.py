"""Tests for finance_agent.tui.services -- TUIServices."""

from __future__ import annotations

from finance_agent.tui.services import TUIServices

# ── _extract_order_id (static, pure) ───────────────────────────────


class TestExtractOrderId:
    def test_order_id_from_order_key(self):
        result = TUIServices._extract_order_id({"order": {"order_id": "ORD-123"}})
        assert result == "ORD-123"

    def test_order_id_from_top_level(self):
        result = TUIServices._extract_order_id({"order_id": "ORD-456"})
        assert result == "ORD-456"

    def test_id_fallback(self):
        result = TUIServices._extract_order_id({"order": {"id": "ID-789"}})
        assert result == "ID-789"

    def test_order_id_camelcase(self):
        result = TUIServices._extract_order_id({"orderId": "CAM-1"})
        assert result == "CAM-1"

    def test_non_dict_returns_empty(self):
        assert TUIServices._extract_order_id("not a dict") == ""
        assert TUIServices._extract_order_id(None) == ""
        assert TUIServices._extract_order_id(42) == ""

    def test_empty_dict_returns_empty(self):
        assert TUIServices._extract_order_id({}) == ""

    def test_nested_order_empty(self):
        assert TUIServices._extract_order_id({"order": {}}) == ""


# ── validate_execution (pure, sync) ───────────────────────────────


class TestValidateExecution:
    def test_within_limits_returns_none(self, services, sample_group):
        assert services.validate_execution(sample_group) is None

    def test_kalshi_over_limit(self, services, sample_group):
        sample_group["legs"] = [
            {"exchange": "kalshi", "price_cents": 50, "quantity": 300},
        ]
        error = services.validate_execution(sample_group)
        assert error is not None
        assert "kalshi" in error.lower()

    def test_empty_legs_passes(self, services):
        assert services.validate_execution({"legs": []}) is None

    def test_missing_legs_key_passes(self, services):
        assert services.validate_execution({}) is None


# ── get_portfolio (async) ──────────────────────────────────────────


async def test_get_portfolio(services, mock_kalshi):
    portfolio = await services.get_portfolio()
    assert "kalshi" in portfolio
    mock_kalshi.get_balance.assert_called_once()
    mock_kalshi.get_positions.assert_called_once()


# ── get_orders (async) ─────────────────────────────────────────────


async def test_get_orders(services):
    orders = await services.get_orders()
    assert "kalshi" in orders


async def test_get_orders_kalshi_only(services):
    orders = await services.get_orders(exchange="kalshi")
    assert "kalshi" in orders


# ── execute_order (async) ──────────────────────────────────────────


async def test_execute_order_kalshi(services, mock_kalshi):
    mock_kalshi.create_order.return_value = {"order": {"order_id": "K-ORD-1"}}
    leg = {
        "exchange": "kalshi",
        "market_id": "K-MKT-1",
        "action": "buy",
        "side": "yes",
        "quantity": 10,
        "price_cents": 45,
        "order_type": "limit",
    }
    result = await services.execute_order(leg)
    assert result["order"]["order_id"] == "K-ORD-1"
    mock_kalshi.create_order.assert_called_once()


# ── execute_recommendation_group (async, integration) ──────────────


async def test_execute_group_success(services, mock_kalshi, db, session_id):
    from unittest.mock import AsyncMock

    mock_kalshi.create_order.return_value = {"order": {"order_id": "K-ORD-1"}}
    # Mock orderbook to match leg prices (avoid slippage rejection)
    mock_kalshi.get_orderbook = AsyncMock(return_value={"yes": [[45, 100]], "no": [[55, 100]]})

    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test bracket arb",
        estimated_edge_pct=7.0,
        equivalence_notes="Same event, mutually exclusive",
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Leg 1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "market_title": "Leg 2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
        ],
    )
    results = await services.execute_recommendation_group(group_id)
    assert len(results) == 2
    assert all(r["status"] == "executed" for r in results)

    group = db.get_group(group_id)
    assert group["status"] == "executed"


async def test_execute_group_validation_failure(services, db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Too expensive",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Expensive",
                "action": "buy",
                "side": "yes",
                "quantity": 500,  # 500 * 50 / 100 = $250 > $100 limit
                "price_cents": 50,
            },
        ],
    )
    results = await services.execute_recommendation_group(group_id)
    assert all(r["status"] == "rejected" for r in results)
    group = db.get_group(group_id)
    assert group["status"] == "rejected"


async def test_execute_group_partial_failure(services, mock_kalshi, db, session_id):
    from unittest.mock import AsyncMock

    mock_kalshi.create_order.side_effect = [
        {"order": {"order_id": "K-ORD-1"}},  # first leg succeeds
        Exception("API error"),  # second leg fails
    ]

    mock_kalshi.get_orderbook = AsyncMock(return_value={"yes": [[45, 100]], "no": [[55, 100]]})

    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Partial",
        estimated_edge_pct=5.0,
        equivalence_notes="Test",
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Leg 1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "market_title": "Leg 2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
        ],
    )
    results = await services.execute_recommendation_group(group_id)
    statuses = {r["status"] for r in results}
    assert "executed" in statuses
    assert "failed" in statuses
    group = db.get_group(group_id)
    assert group["status"] == "partial"


async def test_execute_group_not_found(services):
    results = await services.execute_recommendation_group(99999)
    assert results == []


# ── reject_group (async) ──────────────────────────────────────────


async def test_reject_group(services, db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Will reject",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Reject me",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
        ],
    )
    await services.reject_group(group_id)
    group = db.get_group(group_id)
    assert group["status"] == "rejected"
    assert group["legs"][0]["status"] == "rejected"


# ── cancel_order (async) ──────────────────────────────────────────


async def test_cancel_order_kalshi(services, mock_kalshi):
    mock_kalshi.cancel_order.return_value = {"status": "cancelled"}
    await services.cancel_order("kalshi", "ORD-1")
    mock_kalshi.cancel_order.assert_called_once_with("ORD-1")


async def test_cancel_order_forwards_to_kalshi(services, mock_kalshi):
    """cancel_order always forwards to Kalshi regardless of exchange param."""
    mock_kalshi.cancel_order.return_value = {"status": "cancelled"}
    await services.cancel_order("kalshi", "ORD-2")
    mock_kalshi.cancel_order.assert_called_with("ORD-2")
