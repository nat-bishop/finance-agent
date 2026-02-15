"""Async service layer wrapping DB + exchange clients for the TUI."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..config import TradingConfig
from ..database import AgentDatabase
from ..kalshi_client import KalshiAPIClient
from ..polymarket_client import PM_INTENT_MAP, PolymarketAPIClient, cents_to_usd


class TUIServices:
    """Async wrappers around sync DB reads and exchange API calls."""

    def __init__(
        self,
        db: AgentDatabase,
        kalshi: KalshiAPIClient,
        polymarket: PolymarketAPIClient | None,
        config: TradingConfig,
        session_id: str,
    ) -> None:
        self.db = db
        self._kalshi = kalshi
        self._pm = polymarket
        self._config = config
        self._session_id = session_id
        self._executor = ThreadPoolExecutor(max_workers=4)

    def _loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_event_loop()

    # ── Portfolio ──────────────────────────────────────────────────

    async def get_portfolio(self) -> dict[str, Any]:
        """Fetch balances and positions from both exchanges."""
        loop = self._loop()
        data: dict[str, Any] = {}

        data["kalshi"] = {
            "balance": await loop.run_in_executor(self._executor, self._kalshi.get_balance),
            "positions": await loop.run_in_executor(self._executor, self._kalshi.get_positions),
        }

        if self._pm:
            data["polymarket"] = {
                "balance": await loop.run_in_executor(self._executor, self._pm.get_balance),
                "positions": await loop.run_in_executor(self._executor, self._pm.get_positions),
            }

        return data

    async def get_orders(self, exchange: str | None = None) -> dict[str, Any]:
        """Fetch resting orders from exchange(s)."""
        loop = self._loop()
        data: dict[str, Any] = {}

        if exchange in ("kalshi", None):
            data["kalshi"] = await loop.run_in_executor(
                self._executor,
                lambda: self._kalshi.get_orders(status="resting"),
            )
        if exchange in ("polymarket", None) and self._pm:
            data["polymarket"] = await loop.run_in_executor(
                self._executor,
                lambda: self._pm.get_orders(status="resting"),
            )

        return data

    # ── Recommendations ───────────────────────────────────────────

    def get_pending_recs(self) -> list[dict[str, Any]]:
        """Get pending recommendations (sync, fast DB read)."""
        return self.db.get_pending_recommendations()

    def get_recommendations(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Get filtered recommendations (sync, fast DB read)."""
        return self.db.get_recommendations(**kwargs)

    # ── Order execution ───────────────────────────────────────────

    def validate_execution(self, recs: list[dict[str, Any]]) -> str | None:
        """Check position limits. Returns error message or None if valid."""
        for rec in recs:
            exchange = rec["exchange"]
            if exchange == "kalshi":
                max_usd = self._config.kalshi_max_position_usd
            else:
                max_usd = self._config.polymarket_max_position_usd

            cost_usd = rec["price_cents"] * rec["quantity"] / 100
            if cost_usd > max_usd:
                return f"Order ${cost_usd:.2f} exceeds {exchange} limit ${max_usd:.2f}"
        return None

    async def execute_order(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Place a single order based on a recommendation."""
        loop = self._loop()
        exchange = rec["exchange"]

        if exchange == "kalshi":
            price_key = "yes_price" if rec["side"] == "yes" else "no_price"
            params = {
                "ticker": rec["market_id"],
                "action": rec["action"],
                "side": rec["side"],
                "count": rec["quantity"],
                "order_type": rec.get("order_type", "limit"),
                price_key: rec["price_cents"],
            }
            return await loop.run_in_executor(
                self._executor,
                lambda: self._kalshi.create_order(**params),
            )
        else:
            if not self._pm:
                raise ValueError("Polymarket not enabled")
            intent = PM_INTENT_MAP[(rec["action"], rec["side"])]
            params_pm = {
                "slug": rec["market_id"],
                "intent": intent,
                "order_type": "ORDER_TYPE_LIMIT",
                "price": cents_to_usd(rec["price_cents"]),
                "quantity": rec["quantity"],
            }
            return await loop.run_in_executor(
                self._executor,
                lambda: self._pm.create_order(**params_pm),  # type: ignore[union-attr]
            )

    async def execute_recommendation_group(
        self, group_id: str | None, rec_ids: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Execute all legs in a recommendation group (or specific recs by ID).

        Returns per-leg results with status and order_id or error.
        """
        if rec_ids:
            recs = [r for r in self.db.get_pending_recommendations() if r["id"] in rec_ids]
        elif group_id:
            recs = [r for r in self.db.get_pending_recommendations() if r["group_id"] == group_id]
        else:
            return []

        # Validate limits
        error = self.validate_execution(recs)
        if error:
            return [{"rec_id": r["id"], "status": "rejected", "error": error} for r in recs]

        results = []
        for rec in recs:
            try:
                result = await self.execute_order(rec)
                order_id = ""
                # Try to extract order_id from exchange response
                if isinstance(result, dict):
                    order = result.get("order", result)
                    order_id = str(
                        order.get("order_id", order.get("id", order.get("orderId", "")))
                    )

                self.db.log_trade(
                    session_id=self._session_id,
                    ticker=rec["market_id"],
                    action=rec["action"],
                    side=rec["side"],
                    count=rec["quantity"],
                    price_cents=rec["price_cents"],
                    order_type=rec.get("order_type", "limit"),
                    order_id=order_id,
                    status="placed",
                    result_json=json.dumps(result, default=str),
                    exchange=rec["exchange"],
                )
                self.db.update_recommendation_status(rec["id"], "executed", order_id)
                results.append(
                    {
                        "rec_id": rec["id"],
                        "status": "executed",
                        "order_id": order_id,
                    }
                )
            except Exception as e:
                self.db.update_recommendation_status(rec["id"], "rejected")
                results.append(
                    {
                        "rec_id": rec["id"],
                        "status": "failed",
                        "error": str(e),
                    }
                )

        return results

    async def reject_recommendation(self, rec_id: int) -> None:
        """Mark a recommendation as rejected."""
        self.db.update_recommendation_status(rec_id, "rejected")

    # ── Order management ──────────────────────────────────────────

    async def cancel_order(self, exchange: str, order_id: str) -> dict[str, Any]:
        """Cancel an order on the specified exchange."""
        loop = self._loop()
        if exchange == "kalshi":
            return await loop.run_in_executor(
                self._executor,
                lambda: self._kalshi.cancel_order(order_id),
            )
        elif self._pm:
            return await loop.run_in_executor(
                self._executor,
                lambda: self._pm.cancel_order(order_id),  # type: ignore[union-attr]
            )
        raise ValueError(f"Unknown exchange: {exchange}")

    async def amend_order(
        self,
        order_id: str,
        *,
        price: int | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        """Amend a Kalshi order (price and/or count)."""
        loop = self._loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: self._kalshi.amend_order(order_id, price=price, count=count),
        )

    # ── DB queries ────────────────────────────────────────────────

    def get_trades(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.db.get_trades(**kwargs)

    def get_sessions(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.db.get_sessions(**kwargs)

    def get_signals(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self.db.get_signals(**kwargs)

    def get_session_state(self) -> dict[str, Any]:
        return self.db.get_session_state()
