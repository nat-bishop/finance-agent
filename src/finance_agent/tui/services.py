"""Async service layer wrapping DB + exchange clients for the TUI."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from ..config import Credentials, TradingConfig
from ..database import AgentDatabase
from ..fees import best_price_and_depth, compute_arb_edge, leg_fee
from ..kalshi_client import KalshiAPIClient
from ..polymarket_client import PM_INTENT_MAP, PolymarketAPIClient, cents_to_usd
from ..ws_monitor import FillMonitor
from .messages import ExecutionProgress, FillReceived

logger = logging.getLogger(__name__)


class TUIServices:
    """Async wrappers around DB reads and exchange API calls."""

    def __init__(
        self,
        db: AgentDatabase,
        kalshi: KalshiAPIClient,
        polymarket: PolymarketAPIClient | None,
        config: TradingConfig,
        session_id: str,
        credentials: Credentials | None = None,
    ) -> None:
        self.db = db
        self._kalshi = kalshi
        self._pm = polymarket
        self._config = config
        self._session_id = session_id
        self._credentials = credentials
        self._fill_monitor: FillMonitor | None = None

    def _get_fill_monitor(self) -> FillMonitor:
        if not self._fill_monitor and self._credentials:
            self._fill_monitor = FillMonitor(self._credentials, self._config)
        if not self._fill_monitor:
            raise RuntimeError("Fill monitor unavailable — no credentials provided")
        return self._fill_monitor

    # ── Portfolio ──────────────────────────────────────────────────

    async def get_portfolio(self) -> dict[str, Any]:
        """Fetch balances and positions from both exchanges."""
        data: dict[str, Any] = {}

        # Fire all calls in parallel
        coros = [self._kalshi.get_balance(), self._kalshi.get_positions()]
        labels = ["k_balance", "k_positions"]
        if self._pm:
            coros.extend([self._pm.get_balance(), self._pm.get_positions()])
            labels.extend(["pm_balance", "pm_positions"])

        results = dict(zip(labels, await asyncio.gather(*coros), strict=True))
        data["kalshi"] = {
            "balance": results["k_balance"],
            "positions": results["k_positions"],
        }
        if self._pm:
            data["polymarket"] = {
                "balance": results["pm_balance"],
                "positions": results["pm_positions"],
            }

        return data

    async def get_orders(self, exchange: str | None = None) -> dict[str, Any]:
        """Fetch resting orders from exchange(s)."""
        coros: list = []
        keys: list[str] = []
        if exchange in ("kalshi", None):
            coros.append(self._kalshi.get_orders(status="resting"))
            keys.append("kalshi")
        if exchange in ("polymarket", None) and self._pm:
            coros.append(self._pm.get_orders(status="resting"))
            keys.append("polymarket")

        values = await asyncio.gather(*coros)
        return dict(zip(keys, values, strict=True))

    # ── Recommendations ───────────────────────────────────────────

    def get_pending_groups(self) -> list[dict[str, Any]]:
        """Get pending recommendation groups with legs (sync, fast DB read)."""
        return self.db.get_pending_groups()

    def get_recommendations(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Get filtered recommendation groups with legs (sync, fast DB read)."""
        return self.db.get_recommendations(**kwargs)

    # ── Orderbook fetching ────────────────────────────────────────

    async def _fetch_orderbook(self, exchange: str, market_id: str) -> dict[str, Any]:
        """Fetch orderbook from exchange."""
        if exchange == "kalshi":
            return await self._kalshi.get_orderbook(market_id)
        if self._pm:
            return await self._pm.get_orderbook(market_id)
        raise ValueError(f"Exchange {exchange} not available")

    # ── Order execution ───────────────────────────────────────────

    def validate_execution(self, group: dict[str, Any]) -> str | None:
        """Check position limits with fee-aware cost. Returns error or None."""
        total_cost = 0.0
        for leg in group.get("legs", []):
            exchange = leg["exchange"]
            price_cents = leg.get("price_cents", 0)
            quantity = leg.get("quantity", 0)
            if not price_cents or not quantity:
                return f"Leg {leg.get('market_id')} has no computed price/quantity"

            cost_usd = price_cents * quantity / 100
            fee = leg_fee(exchange, quantity, price_cents, maker=leg.get("is_maker", False))
            total_with_fee = cost_usd + fee
            total_cost += total_with_fee

            if exchange == "kalshi":
                max_usd = self._config.kalshi_max_position_usd
            else:
                max_usd = self._config.polymarket_max_position_usd

            if total_with_fee > max_usd:
                return (
                    f"Order ${total_with_fee:.2f} (incl ${fee:.4f} fee) "
                    f"exceeds {exchange} limit ${max_usd:.2f}"
                )

        if total_cost > self._config.max_portfolio_usd:
            return (
                f"Total group cost ${total_cost:.2f} exceeds "
                f"portfolio limit ${self._config.max_portfolio_usd:.2f}"
            )
        return None

    async def execute_order(self, leg: dict[str, Any]) -> dict[str, Any]:
        """Place a single order based on a recommendation leg."""
        exchange = leg["exchange"]
        logger.info(
            "Executing order: %s %s %s on %s @ %dc x%d (maker=%s)",
            leg["action"],
            leg["side"],
            leg["market_id"],
            exchange,
            leg["price_cents"],
            leg["quantity"],
            leg.get("is_maker", False),
        )

        if exchange == "kalshi":
            price_key = "yes_price" if leg["side"] == "yes" else "no_price"
            params = {
                "ticker": leg["market_id"],
                "action": leg["action"],
                "side": leg["side"],
                "count": leg["quantity"],
                "order_type": leg.get("order_type", "limit"),
                price_key: leg["price_cents"],
            }
            return await self._kalshi.create_order(**params)

        if not self._pm:
            raise ValueError("Polymarket not enabled")
        intent = PM_INTENT_MAP[(leg["action"], leg["side"])]
        params_pm = {
            "slug": leg["market_id"],
            "intent": intent,
            "order_type": "ORDER_TYPE_LIMIT",
            "price": cents_to_usd(leg["price_cents"]),
            "quantity": leg["quantity"],
        }
        return await self._pm.create_order(**params_pm)

    # ── Execution helpers ─────────────────────────────────────────

    def _reject_all_legs(
        self, group_id: int, legs: list[dict[str, Any]], error: str
    ) -> list[dict[str, Any]]:
        """Mark group rejected and return rejection results for all legs."""
        self.db.update_group_status(group_id, "rejected")
        return [{"leg_id": lg["id"], "status": "rejected", "error": error} for lg in legs]

    @staticmethod
    def _parse_fill(fill: dict[str, Any], leg: dict[str, Any]) -> tuple[int, int]:
        """Extract fill price (cents) and quantity from an exchange fill response."""
        price = fill.get("fill_price_cents", fill.get("price", leg["price_cents"]))
        qty = fill.get("fill_quantity", fill.get("quantity", leg["quantity"]))
        if isinstance(price, str):
            price = int(float(price) * 100)
        return int(price), int(qty)

    async def _execute_and_log_leg(self, leg: dict[str, Any]) -> dict[str, Any]:
        """Place order, log trade, update leg status. Returns result dict with order_id."""
        result = await self.execute_order(leg)
        order_id = self._extract_order_id(result)
        self.db.log_trade(
            session_id=self._session_id,
            ticker=leg["market_id"],
            action=leg["action"],
            side=leg["side"],
            quantity=leg["quantity"],
            price_cents=leg["price_cents"],
            order_type="limit",
            order_id=order_id,
            status="placed",
            result_json=json.dumps(result, default=str),
            exchange=leg["exchange"],
            leg_id=leg["id"],
        )
        self.db.update_leg_status(leg["id"], "executed", order_id)
        return {"leg_id": leg["id"], "status": "executed", "order_id": order_id}

    async def _refresh_legs_and_validate(
        self,
        group_id: int,
        group: dict[str, Any],
        legs: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
        """Re-fetch orderbooks, recompute edge, validate limits.

        Returns (refreshed_legs, None) on success or (None, rejection_results) on failure.
        """
        refreshed_legs: list[dict[str, Any]] = []
        for leg in legs:
            try:
                ob = await self._fetch_orderbook(leg["exchange"], leg["market_id"])
            except Exception as e:
                return None, self._reject_all_legs(group_id, legs, f"Orderbook fetch failed: {e}")

            side = leg.get("side", "yes")
            price, depth = best_price_and_depth(ob, side)

            rec_price = leg.get("price_cents")
            if price and rec_price:
                slippage = abs(price - rec_price)
                if slippage > self._config.max_slippage_cents:
                    error = (
                        f"Price moved {slippage}c on {leg['market_id']} "
                        f"(was {rec_price}c, now {price}c, "
                        f"max slippage {self._config.max_slippage_cents}c)"
                    )
                    logger.warning("Group %d rejected: %s", group_id, error)
                    return None, self._reject_all_legs(group_id, legs, error)

            refreshed_legs.append(
                {
                    **leg,
                    "price_cents": price or leg.get("price_cents", 0),
                    "depth": depth,
                }
            )

        # Recompute edge with fresh prices
        contracts = refreshed_legs[0].get("quantity", 0) if refreshed_legs else 0
        if contracts > 0:
            fee_legs = [
                {
                    "exchange": lg["exchange"],
                    "price_cents": lg["price_cents"],
                    "maker": lg.get("is_maker", False),
                }
                for lg in refreshed_legs
            ]
            edge = compute_arb_edge(fee_legs, contracts)
            if edge["net_edge_pct"] < self._config.min_edge_pct:
                error = (
                    f"Edge evaporated: was {group.get('computed_edge_pct', '?')}%, "
                    f"now {edge['net_edge_pct']}% (min {self._config.min_edge_pct}%)"
                )
                logger.warning("Group %d rejected: %s", group_id, error)
                return None, self._reject_all_legs(group_id, legs, error)

            self.db.update_group_computed_fields(
                group_id, edge["net_edge_pct"], edge["total_fees_usd"]
            )

        # Validate position limits
        limit_error = self.validate_execution({"legs": refreshed_legs})
        if limit_error:
            logger.warning("Group %d rejected: %s", group_id, limit_error)
            return None, self._reject_all_legs(group_id, legs, limit_error)

        return refreshed_legs, None

    @staticmethod
    def _derive_group_status(results: list[dict[str, Any]], total_legs: int) -> str:
        """Derive group status from per-leg execution results."""
        executed = sum(1 for r in results if r["status"] == "executed")
        if executed == total_legs:
            return "executed"
        return "rejected" if executed == 0 else "partial"

    # ── Group execution orchestrator ───────────────────────────

    async def execute_recommendation_group(
        self,
        group_id: int,
        on_progress: Callable[[ExecutionProgress | FillReceived], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute all legs using leg-in strategy with fill monitoring.

        1. Re-fetch orderbooks, recompute prices/quantities/edge
        2. Validate edge still exists (slippage check)
        3. Place harder leg first as maker, wait for fill
        4. Place easier leg as taker
        5. Handle failures: cancel/unwind as needed
        """

        def _emit(msg: ExecutionProgress | FillReceived) -> None:
            if on_progress:
                on_progress(msg)

        group = self.db.get_group(group_id)
        if not group:
            return []

        legs = group.get("legs", [])
        logger.info("Executing recommendation group %d (%d legs)", group_id, len(legs))
        _emit(ExecutionProgress(group_id, "recomputing_edge"))

        # Phase 1: Refresh orderbooks, recompute edge, validate limits
        refreshed_legs, error_results = await self._refresh_legs_and_validate(
            group_id, group, legs
        )
        if error_results is not None:
            return error_results
        if refreshed_legs is None:
            raise RuntimeError("refreshed_legs unexpectedly None after validation")

        # Phase 2: Leg-in execution — harder leg as maker, easier as taker
        sorted_legs = sorted(refreshed_legs, key=lambda lg: lg.get("depth", 0))
        maker_leg = sorted_legs[0]
        taker_legs = sorted_legs[1:]

        results: list[dict[str, Any]] = []
        try:
            fill_monitor = self._get_fill_monitor()
        except RuntimeError:
            logger.error(
                "Fill monitor unavailable — cannot safely execute without fill confirmation"
            )
            return self._reject_all_legs(
                group_id,
                legs,
                "Fill monitor unavailable — execution requires WebSocket fill confirmation",
            )

        # Place maker leg
        _emit(ExecutionProgress(group_id, "placing_maker", maker_leg.get("id")))
        try:
            maker_result = await self._execute_and_log_leg(maker_leg)
            results.append(maker_result)
            order_id = maker_result["order_id"]
        except Exception as e:
            logger.error("Maker leg %d failed: %s", maker_leg["id"], e)
            self.db.update_leg_status(maker_leg["id"], "rejected")
            return self._reject_all_legs(group_id, legs, str(e))

        # Wait for maker fill
        _emit(ExecutionProgress(group_id, "waiting_for_maker_fill", maker_leg.get("id")))
        logger.info(
            "Waiting for maker fill on %s (timeout %ds)",
            order_id,
            self._config.execution_timeout_seconds,
        )
        fill = await fill_monitor.wait_for_fill(
            maker_leg["exchange"],
            order_id,
            self._config.execution_timeout_seconds,
            market_slug=maker_leg["market_id"],
        )
        if not fill:
            logger.warning("Maker leg timed out, cancelling order %s", order_id)
            try:
                await self.cancel_order(maker_leg["exchange"], order_id)
            except Exception as cancel_err:
                logger.error("Failed to cancel maker leg: %s", cancel_err)
            self.db.update_group_status(group_id, "rejected")
            return [
                {
                    "leg_id": maker_leg["id"],
                    "status": "rejected",
                    "error": f"Maker leg timed out after {self._config.execution_timeout_seconds}s",
                }
            ]

        fill_price, fill_qty = self._parse_fill(fill, maker_leg)
        self.db.update_leg_fill(maker_leg["id"], fill_price, fill_qty)
        logger.info("Maker fill confirmed: %d contracts @ %dc", fill_qty, fill_price)
        _emit(FillReceived(order_id, fill_price, fill_qty, maker_leg["exchange"]))
        _emit(ExecutionProgress(group_id, "maker_filled", maker_leg.get("id")))

        # Place taker legs
        for taker_leg in taker_legs:
            _emit(ExecutionProgress(group_id, "placing_taker", taker_leg.get("id")))
            try:
                taker_result = await self._execute_and_log_leg(taker_leg)
                results.append(taker_result)
                taker_order_id = taker_result["order_id"]

                taker_fill = await fill_monitor.wait_for_fill(
                    taker_leg["exchange"],
                    taker_order_id,
                    30,
                    market_slug=taker_leg["market_id"],
                )
                if taker_fill:
                    tp, tq = self._parse_fill(taker_fill, taker_leg)
                    self.db.update_leg_fill(taker_leg["id"], tp, tq)
                    _emit(FillReceived(taker_order_id, tp, tq, taker_leg["exchange"]))
                else:
                    logger.warning("Taker leg didn't fill within 30s — attempting unwind")
                    await self._attempt_unwind(maker_leg, results)
                    self.db.update_group_status(group_id, "partial")
                    return results

            except Exception as e:
                logger.error("Taker leg %d failed: %s", taker_leg["id"], e)
                self.db.update_leg_status(taker_leg["id"], "rejected")
                results.append({"leg_id": taker_leg["id"], "status": "failed", "error": str(e)})
                await self._attempt_unwind(maker_leg, results)

        # Finalize
        group_status = self._derive_group_status(results, len(legs))
        self.db.update_group_status(group_id, group_status)
        executed = sum(1 for r in results if r["status"] == "executed")
        logger.info(
            "Group %d result: %s (%d/%d executed)",
            group_id,
            group_status,
            executed,
            len(legs),
        )
        _emit(ExecutionProgress(group_id, f"complete:{group_status}"))

        await fill_monitor.close()
        self._fill_monitor = None

        return results

    async def _attempt_unwind(
        self, filled_leg: dict[str, Any], results: list[dict[str, Any]]
    ) -> None:
        """Attempt to unwind a filled leg by placing an opposite order."""
        logger.warning(
            "Attempting to unwind filled leg %d on %s",
            filled_leg["id"],
            filled_leg["exchange"],
        )
        # Reverse: if we bought YES, now sell YES
        reverse_action = "sell" if filled_leg["action"] == "buy" else "buy"
        unwind_leg = {
            **filled_leg,
            "action": reverse_action,
            # Use same price — market order equivalent for limit
        }
        try:
            result = await self.execute_order(unwind_leg)
            order_id = self._extract_order_id(result)
            logger.info("Unwind order placed: %s", order_id)
            results.append(
                {
                    "leg_id": filled_leg["id"],
                    "status": "unwind_placed",
                    "order_id": order_id,
                }
            )
        except Exception as e:
            logger.error("Unwind failed for leg %d: %s", filled_leg["id"], e)
            results.append(
                {
                    "leg_id": filled_leg["id"],
                    "status": "unwind_failed",
                    "error": str(e),
                }
            )

    @staticmethod
    def _extract_order_id(result: Any) -> str:
        """Extract order_id from an exchange API response."""
        if not isinstance(result, dict):
            return ""
        order = result.get("order", result)
        return str(order.get("order_id", order.get("id", order.get("orderId", ""))))

    async def reject_group(self, group_id: int) -> None:
        """Mark an entire recommendation group as rejected."""
        logger.info("Rejected recommendation group %d", group_id)
        group = self.db.get_group(group_id)
        if group:
            for leg in group.get("legs", []):
                self.db.update_leg_status(leg["id"], "rejected")
        self.db.update_group_status(group_id, "rejected")

    # ── Order management ──────────────────────────────────────────

    async def cancel_order(self, exchange: str, order_id: str) -> dict[str, Any]:
        """Cancel an order on the specified exchange."""
        logger.info("Cancelling order %s on %s", order_id, exchange)
        if exchange == "kalshi":
            return await self._kalshi.cancel_order(order_id)
        if self._pm:
            return await self._pm.cancel_order(order_id)
        raise ValueError(f"Unknown exchange: {exchange}")

    # ── DB queries ────────────────────────────────────────────────

    def get_trades(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.db.get_trades(**kwargs)

    def get_sessions(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.db.get_sessions(**kwargs)
