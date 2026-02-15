"""Audit hooks -- trade logging to SQLite + approval flow."""

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
    """Return hooks dict for trade validation, auto-approve, audit, and session lifecycle."""
    session_start = time.time()
    trade_count = {"placed": 0, "amended": 0, "cancelled": 0}

    # -- 1. Auto-approve reads --

    async def auto_approve_reads(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        return {"permissionDecision": "allow"}

    # -- 2. Trade validation (unified place_order) --

    async def validate_and_ask_trade(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        ti = input_data.get("tool_input", {})
        exchange = ti.get("exchange", "?")
        orders = ti.get("orders", [])

        lines = []
        total_cost = 0.0
        for o in orders:
            price = o.get("price_cents", 0)
            qty = o.get("quantity", 0)
            cost = (qty * price) / 100
            total_cost += cost
            lines.append(
                f"  {o.get('action', '?').upper()} {qty}x "
                f"{o.get('side', '?').upper()} on {o.get('market_id', '?')} "
                f"@ {price}c = ${cost:.2f}"
            )

        summary = "\n".join(lines) if lines else "  (no orders)"
        label = (
            f"{exchange.upper()} ORDER"
            if len(orders) == 1
            else f"{exchange.upper()} BATCH ({len(orders)} orders)"
        )

        return {
            "permissionDecision": "ask",
            "systemMessage": (f"{label} | Total: ${total_cost:.2f}\n{summary}"),
        }

    # -- 3. Amend order --

    async def validate_and_ask_amend(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        ti = input_data.get("tool_input", {})
        order_id = ti.get("order_id", "?")
        parts = [f"AMEND ORDER: {order_id}"]
        if ti.get("price_cents"):
            parts.append(f"New price: {ti['price_cents']}c")
        if ti.get("quantity"):
            parts.append(f"New qty: {ti['quantity']}")
        return {
            "permissionDecision": "ask",
            "systemMessage": " | ".join(parts),
        }

    # -- 4. Cancel order --

    async def ask_cancel(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        ti = input_data.get("tool_input", {})
        exchange = ti.get("exchange", "?")
        ids = ti.get("order_ids", [])
        return {
            "permissionDecision": "ask",
            "systemMessage": f"CANCEL {exchange.upper()}: {len(ids)} order(s) — {', '.join(ids[:5])}",
        }

    # -- 5. Trade audit (PostToolUse) --

    async def audit_trade_result(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_response = input_data.get("tool_response", "")

        # Parse response
        if isinstance(tool_response, str):
            try:
                result = json.loads(tool_response)
            except (json.JSONDecodeError, TypeError):
                result = {"raw": tool_response}
        elif isinstance(tool_response, dict):
            result = tool_response
        else:
            result = {}

        if "place_order" in tool_name:
            exchange = tool_input.get("exchange", "kalshi")
            orders = tool_input.get("orders", [])
            for o in orders:
                trade_count["placed"] += 1
                # Extract order_id from result
                order_id = None
                if isinstance(result, dict):
                    order = result.get("order", result)
                    order_id = order.get("order_id") or order.get("id")

                action = o.get("action", "")
                side = o.get("side", "")

                db.log_trade(
                    session_id=session_id,
                    exchange=exchange,
                    ticker=o.get("market_id", ""),
                    action=action,
                    side=side,
                    count=o.get("quantity", 0),
                    price_cents=o.get("price_cents"),
                    order_type=o.get("type", "limit"),
                    order_id=order_id,
                    status="placed",
                    result_json=json.dumps(result, default=str),
                )

        elif "amend_order" in tool_name:
            trade_count["amended"] += 1

        elif "cancel_order" in tool_name:
            trade_count["cancelled"] += 1

        return {}

    # -- 6. Session end (Stop) --

    async def session_end(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        duration = time.time() - session_start
        db.end_session(
            session_id=session_id,
            summary=(
                f"Duration: {duration:.0f}s | "
                f"Orders placed: {trade_count['placed']} | "
                f"Amended: {trade_count['amended']} | "
                f"Cancelled: {trade_count['cancelled']}"
            ),
            trades_placed=trade_count["placed"],
        )
        return {}

    return {
        "PreToolUse": [
            HookMatcher(
                matcher=(
                    "mcp__markets__search_markets|mcp__markets__get_|mcp__db__|Read|Glob|Grep"
                ),
                hooks=[auto_approve_reads],
            ),
            HookMatcher(
                matcher="mcp__markets__place_order",
                hooks=[validate_and_ask_trade],
            ),
            HookMatcher(
                matcher="mcp__markets__amend_order",
                hooks=[validate_and_ask_amend],
            ),
            HookMatcher(
                matcher="mcp__markets__cancel_order",
                hooks=[ask_cancel],
            ),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher=(
                    "mcp__markets__place_order"
                    "|mcp__markets__amend_order"
                    "|mcp__markets__cancel_order"
                ),
                hooks=[audit_trade_result],
            ),
        ],
        "Stop": [
            HookMatcher(hooks=[session_end]),
        ],
    }
