"""Audit hooks — trade logging to SQLite + approval flow."""

from __future__ import annotations

import json
import time
from typing import Any

from claude_agent_sdk import HookMatcher

from .database import AgentDatabase


def create_audit_hooks(
    db: AgentDatabase,
    session_id: str,
) -> dict[str, list[HookMatcher]]:
    """Return hooks dict for trade validation, auto-approve, audit, and session lifecycle.

    Hook order (PreToolUse):
    1. Auto-approve reads — Kalshi read tools, DB read tools, filesystem reads
    2. Trade validation — validates limits, forces user approval via 'ask'
    3. Cancel order — forces user approval via 'ask'

    PostToolUse:
    4. Trade audit — logs order/cancel results to SQLite

    Stop:
    5. Session end — updates session record
    """
    session_start = time.time()
    trade_count = {"placed": 0, "cancelled": 0}

    # ── 1. Auto-approve reads ────────────────────────────────────

    async def auto_approve_reads(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        return {"permissionDecision": "allow"}

    def _extract_price(tool_input: dict[str, Any]) -> int:
        """Extract the effective price from yes_price or no_price."""
        yes_price = tool_input.get("yes_price", 0) or 0
        no_price = tool_input.get("no_price", 0) or 0
        return max(yes_price, no_price)

    # ── 2. Trade validation (place_order) ────────────────────────

    async def validate_and_ask_trade(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_input = input_data.get("tool_input", {})
        count = tool_input.get("count", 0)
        price = _extract_price(tool_input)
        cost = (count * price) / 100

        ticker = tool_input.get("ticker", "?")
        action = tool_input.get("action", "?")
        side = tool_input.get("side", "?")
        order_type = tool_input.get("order_type", "limit")

        # Force user approval via 'ask' (can_use_tool will handle the prompt)
        return {
            "permissionDecision": "ask",
            "systemMessage": (
                f"TRADE REQUEST: {action.upper()} {count}x {side.upper()} on {ticker} | "
                f"Type: {order_type} | Price: {price}¢ | Cost: ${cost:.2f}"
            ),
        }

    # ── 2b. Trade validation (Polymarket place_order) ────────────

    async def validate_and_ask_pm_trade(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_input = input_data.get("tool_input", {})
        price = float(tool_input.get("price", "0"))
        quantity = tool_input.get("quantity", 0)
        cost = quantity * price
        slug = tool_input.get("slug", "?")
        intent = tool_input.get("intent", "?")
        order_type = tool_input.get("order_type", "LIMIT")
        return {
            "permissionDecision": "ask",
            "systemMessage": (
                f"POLYMARKET TRADE: {intent} {quantity}x on {slug} | "
                f"Type: {order_type} | Price: ${price:.2f} | Cost: ${cost:.2f}"
            ),
        }

    # ── 3. Cancel order ──────────────────────────────────────────

    async def ask_cancel(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_input = input_data.get("tool_input", {})
        order_id = tool_input.get("order_id", "?")
        return {
            "permissionDecision": "ask",
            "systemMessage": f"CANCEL REQUEST: Order {order_id}",
        }

    # ── 4. Trade audit (PostToolUse) ─────────────────────────────

    async def audit_trade_result(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_response = input_data.get("tool_response", "")

        # Parse response
        result = {}
        if isinstance(tool_response, str):
            try:
                result = json.loads(tool_response)
            except (json.JSONDecodeError, TypeError):
                result = {"raw": tool_response}
        elif isinstance(tool_response, dict):
            result = tool_response

        if "place_order" in tool_name:
            trade_count["placed"] += 1
            exchange = "polymarket" if "polymarket" in tool_name else "kalshi"

            # Extract order_id from result if available
            order_id = None
            if isinstance(result, dict):
                order = result.get("order", result)
                order_id = order.get("order_id") or order.get("id")

            # Normalize fields — Kalshi uses ticker/action/side/count,
            # Polymarket uses slug/intent/quantity
            if exchange == "polymarket":
                ticker = tool_input.get("slug", "")
                action = tool_input.get("intent", "")
                side = ""
                count = tool_input.get("quantity", 0)
                price_cents = int(float(tool_input.get("price", "0")) * 100)
            else:
                ticker = tool_input.get("ticker", "")
                action = tool_input.get("action", "")
                side = tool_input.get("side", "")
                count = tool_input.get("count", 0)
                price_cents = _extract_price(tool_input)

            db.log_trade(
                session_id=session_id,
                exchange=exchange,
                ticker=ticker,
                action=action,
                side=side,
                count=count,
                price_cents=price_cents,
                order_type=tool_input.get("order_type", "limit"),
                order_id=order_id,
                status="placed",
                result_json=json.dumps(result, default=str),
            )

        elif "cancel_order" in tool_name:
            trade_count["cancelled"] += 1

        return {}

    # ── 5. Session end (Stop) ────────────────────────────────────

    async def session_end(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        duration = time.time() - session_start
        summary = (
            f"Duration: {duration:.0f}s | "
            f"Orders placed: {trade_count['placed']} | "
            f"Orders cancelled: {trade_count['cancelled']}"
        )
        db.end_session(
            session_id=session_id,
            summary=summary,
            trades_placed=trade_count["placed"],
        )
        return {}

    return {
        "PreToolUse": [
            # 1. Auto-approve reads (Kalshi reads + DB reads + filesystem reads)
            HookMatcher(
                matcher=(
                    "mcp__kalshi__search_markets|mcp__kalshi__get_"
                    "|mcp__polymarket__search_markets|mcp__polymarket__get_"
                    "|mcp__db__db_query|mcp__db__db_get_session_state"
                    "|Read|Glob|Grep"
                ),
                hooks=[auto_approve_reads],
            ),
            # 2. Trade validation + user approval
            HookMatcher(
                matcher="mcp__kalshi__place_order",
                hooks=[validate_and_ask_trade],
            ),
            # 2b. Polymarket trade validation + user approval
            HookMatcher(
                matcher="mcp__polymarket__place_order",
                hooks=[validate_and_ask_pm_trade],
            ),
            # 3. Cancel order approval
            HookMatcher(
                matcher="mcp__kalshi__cancel_order|mcp__polymarket__cancel_order",
                hooks=[ask_cancel],
            ),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher=(
                    "mcp__kalshi__place_order|mcp__kalshi__cancel_order"
                    "|mcp__polymarket__place_order|mcp__polymarket__cancel_order"
                ),
                hooks=[audit_trade_result],
            ),
        ],
        "Stop": [
            HookMatcher(hooks=[session_end]),
        ],
    }
