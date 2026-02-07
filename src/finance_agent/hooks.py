"""Audit hooks — trade journal logging in JSONL format."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookMatcher


def create_audit_hooks(journal_dir: Path) -> dict[str, list[HookMatcher]]:
    """Return hooks dict that logs all trades to a JSONL journal.

    Hooks:
    - PreToolUse on place_order/cancel_order: log intent
    - PostToolUse on place_order/cancel_order: log result
    - Stop: log session summary
    """
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_file = journal_dir / "trades.jsonl"

    session_id = str(uuid.uuid4())[:8]
    session_start = time.time()
    trade_count = {"placed": 0, "cancelled": 0}

    def _log(entry: dict) -> None:
        entry["timestamp"] = time.time()
        entry["iso_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entry["session_id"] = session_id
        with open(journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    # ── PreToolUse: log trade intent ────────────────────────────────

    async def pre_trade_hook(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        if "place_order" in tool_name:
            _log(
                {
                    "event": "order_intent",
                    "tool_use_id": tool_use_id,
                    "ticker": tool_input.get("ticker"),
                    "action": tool_input.get("action"),
                    "side": tool_input.get("side"),
                    "count": tool_input.get("count"),
                    "yes_price": tool_input.get("yes_price"),
                    "no_price": tool_input.get("no_price"),
                    "order_type": tool_input.get("order_type", "limit"),
                }
            )
        elif "cancel_order" in tool_name:
            _log(
                {
                    "event": "cancel_intent",
                    "tool_use_id": tool_use_id,
                    "order_id": tool_input.get("order_id"),
                }
            )

        return {}  # No blocking, just logging

    # ── PostToolUse: log trade result ───────────────────────────────

    async def post_trade_hook(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        tool_name = input_data.get("tool_name", "")
        tool_response = input_data.get("tool_response", "")

        # Try to parse the response JSON
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
            _log(
                {
                    "event": "order_result",
                    "tool_use_id": tool_use_id,
                    "result": result,
                }
            )
        elif "cancel_order" in tool_name:
            trade_count["cancelled"] += 1
            _log(
                {
                    "event": "cancel_result",
                    "tool_use_id": tool_use_id,
                    "result": result,
                }
            )

        return {}

    # ── Stop: session summary ───────────────────────────────────────

    async def stop_hook(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict:
        duration = time.time() - session_start
        _log(
            {
                "event": "session_end",
                "duration_seconds": round(duration, 1),
                "orders_placed": trade_count["placed"],
                "orders_cancelled": trade_count["cancelled"],
            }
        )
        return {}

    return {
        "PreToolUse": [
            HookMatcher(
                matcher="mcp__kalshi__place_order|mcp__kalshi__cancel_order",
                hooks=[pre_trade_hook],
            ),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher="mcp__kalshi__place_order|mcp__kalshi__cancel_order",
                hooks=[post_trade_hook],
            ),
        ],
        "Stop": [
            HookMatcher(hooks=[stop_hook]),
        ],
    }
