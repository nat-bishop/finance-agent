"""Audit hooks -- trade logging to SQLite + approval flow."""

from __future__ import annotations

import json
import time
from typing import Any, cast

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookContext, HookEvent, HookInput, HookJSONOutput

from .config import TradingConfig
from .database import AgentDatabase


def _allow() -> HookJSONOutput:
    return cast(
        HookJSONOutput,
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        },
    )


def _ask(message: str) -> HookJSONOutput:
    return cast(HookJSONOutput, {"permissionDecision": "ask", "systemMessage": message})


def _deny(message: str) -> HookJSONOutput:
    return cast(HookJSONOutput, {"permissionDecision": "deny", "systemMessage": message})


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
    trading_config: TradingConfig,
) -> dict[HookEvent, list[HookMatcher]]:
    session_start = time.time()
    trade_count = {"placed": 0, "amended": 0, "cancelled": 0}

    async def auto_approve(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        """Auto-approve all tools except AskUserQuestion (handled by canUseTool)."""
        data = cast(dict[str, Any], input_data)
        if data.get("tool_name") == "AskUserQuestion":
            return cast(HookJSONOutput, {})  # No decision — falls through to canUseTool
        return _allow()

    async def validate_trade(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        data = cast(dict[str, Any], input_data)
        ti = data.get("tool_input", {})
        exchange = ti.get("exchange", "kalshi")
        orders = ti.get("orders", [])

        max_pos = (
            trading_config.kalshi_max_position_usd
            if exchange == "kalshi"
            else trading_config.polymarket_max_position_usd
        )

        lines = []
        total_cost = 0.0
        for o in orders:
            price, qty = o.get("price_cents", 0), o.get("quantity", 0)
            cost = (qty * price) / 100
            total_cost += cost

            if qty > trading_config.max_order_count:
                return _deny(
                    f"Order qty {qty} exceeds max {trading_config.max_order_count} contracts"
                )

            lines.append(
                f"  {o.get('action', '?').upper()} {qty}x "
                f"{o.get('side', '?').upper()} on {o.get('market_id', '?')} "
                f"@ {price}c = ${cost:.2f}"
            )

        if total_cost > max_pos:
            return _deny(f"Total cost ${total_cost:.2f} exceeds {exchange} max ${max_pos:.2f}")

        label = (
            f"{exchange.upper()} ORDER"
            if len(orders) == 1
            else f"{exchange.upper()} BATCH ({len(orders)} orders)"
        )
        summary = "\n".join(lines) or "  (no orders)"
        return _ask(f"{label} | Total: ${total_cost:.2f}\n{summary}")

    async def validate_amend(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        data = cast(dict[str, Any], input_data)
        ti = data.get("tool_input", {})
        parts = [f"AMEND ORDER: {ti.get('order_id', '?')}"]
        if ti.get("price_cents"):
            parts.append(f"New price: {ti['price_cents']}c")
        if ti.get("quantity"):
            parts.append(f"New qty: {ti['quantity']}")
        return _ask(" | ".join(parts))

    async def validate_cancel(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        data = cast(dict[str, Any], input_data)
        ti = data.get("tool_input", {})
        exchange = ti.get("exchange", "?")
        ids = ti.get("order_ids", [])
        return _ask(f"CANCEL {exchange.upper()}: {len(ids)} order(s) — {', '.join(ids[:5])}")

    async def audit_trade_result(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        data = cast(dict[str, Any], input_data)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        result = _parse_result(data.get("tool_response", ""))

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

        return cast(HookJSONOutput, {})

    async def session_end(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
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
        return cast(
            HookJSONOutput,
            {
                "systemMessage": (
                    "Update /workspace/data/watchlist.md with any markets "
                    "to track next session before stopping."
                )
            },
        )

    return {
        "PreToolUse": [
            HookMatcher(matcher="mcp__markets__place_order", hooks=[validate_trade]),
            HookMatcher(matcher="mcp__markets__amend_order", hooks=[validate_amend]),
            HookMatcher(matcher="mcp__markets__cancel_order", hooks=[validate_cancel]),
            HookMatcher(hooks=[auto_approve]),  # catch-all, no matcher
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
