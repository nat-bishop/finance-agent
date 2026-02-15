"""Audit hooks -- trade logging to SQLite + approval flow."""

from __future__ import annotations

import json
import time
from typing import Any

from claude_agent_sdk import HookMatcher

from .database import AgentDatabase


def _ask(message: str) -> dict:
    return {"permissionDecision": "ask", "systemMessage": message}


def _parse_result(tool_response: Any) -> dict:
    if isinstance(tool_response, str):
        try:
            return json.loads(tool_response)
        except (json.JSONDecodeError, TypeError):
            return {"raw": tool_response}
    return tool_response if isinstance(tool_response, dict) else {}


def create_audit_hooks(
    db: AgentDatabase,
    session_id: str,
) -> dict[str, list[HookMatcher]]:
    session_start = time.time()
    trade_count = {"placed": 0, "amended": 0, "cancelled": 0}

    async def auto_approve_reads(input_data: dict, *_: Any) -> dict:
        return {"permissionDecision": "allow"}

    async def validate_trade(input_data: dict, *_: Any) -> dict:
        ti = input_data.get("tool_input", {})
        exchange = ti.get("exchange", "?")
        orders = ti.get("orders", [])

        lines = []
        total_cost = 0.0
        for o in orders:
            price, qty = o.get("price_cents", 0), o.get("quantity", 0)
            cost = (qty * price) / 100
            total_cost += cost
            lines.append(
                f"  {o.get('action', '?').upper()} {qty}x "
                f"{o.get('side', '?').upper()} on {o.get('market_id', '?')} "
                f"@ {price}c = ${cost:.2f}"
            )

        label = (
            f"{exchange.upper()} ORDER"
            if len(orders) == 1
            else f"{exchange.upper()} BATCH ({len(orders)} orders)"
        )
        summary = "\n".join(lines) or "  (no orders)"
        return _ask(f"{label} | Total: ${total_cost:.2f}\n{summary}")

    async def validate_amend(input_data: dict, *_: Any) -> dict:
        ti = input_data.get("tool_input", {})
        parts = [f"AMEND ORDER: {ti.get('order_id', '?')}"]
        if ti.get("price_cents"):
            parts.append(f"New price: {ti['price_cents']}c")
        if ti.get("quantity"):
            parts.append(f"New qty: {ti['quantity']}")
        return _ask(" | ".join(parts))

    async def validate_cancel(input_data: dict, *_: Any) -> dict:
        ti = input_data.get("tool_input", {})
        exchange = ti.get("exchange", "?")
        ids = ti.get("order_ids", [])
        return _ask(f"CANCEL {exchange.upper()}: {len(ids)} order(s) — {', '.join(ids[:5])}")

    async def audit_trade_result(input_data: dict, *_: Any) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        result = _parse_result(input_data.get("tool_response", ""))

        if "place_order" in tool_name:
            exchange = tool_input.get("exchange", "kalshi")
            for o in tool_input.get("orders", []):
                trade_count["placed"] += 1
                order_id = None
                if isinstance(result, dict):
                    order = result.get("order", result)
                    order_id = order.get("order_id") or order.get("id")
                db.log_trade(
                    session_id=session_id,
                    exchange=exchange,
                    ticker=o.get("market_id", ""),
                    action=o.get("action", ""),
                    side=o.get("side", ""),
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

    async def session_end(input_data: dict, *_: Any) -> dict:
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
                matcher="mcp__markets__search_markets|mcp__markets__get_|mcp__db__|Read|Glob|Grep",
                hooks=[auto_approve_reads],
            ),
            HookMatcher(matcher="mcp__markets__place_order", hooks=[validate_trade]),
            HookMatcher(matcher="mcp__markets__amend_order", hooks=[validate_amend]),
            HookMatcher(matcher="mcp__markets__cancel_order", hooks=[validate_cancel]),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher="mcp__markets__place_order"
                "|mcp__markets__amend_order"
                "|mcp__markets__cancel_order",
                hooks=[audit_trade_result],
            ),
        ],
        "Stop": [
            HookMatcher(hooks=[session_end]),
        ],
    }
