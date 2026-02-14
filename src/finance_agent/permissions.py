"""Permission handler -- gates writes, enforces trading limits, handles user interaction."""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .config import PermissionConfig, TradingConfig

# Tools that are always auto-approved (reads + DB + filesystem)
_READ_TOOLS = {
    # Kalshi reads
    "mcp__kalshi__search_markets",
    "mcp__kalshi__get_market_details",
    "mcp__kalshi__get_orderbook",
    "mcp__kalshi__get_event",
    "mcp__kalshi__get_price_history",
    "mcp__kalshi__get_recent_trades",
    "mcp__kalshi__get_portfolio",
    "mcp__kalshi__get_open_orders",
    # Polymarket reads
    "mcp__polymarket__search_markets",
    "mcp__polymarket__get_market_details",
    "mcp__polymarket__get_orderbook",
    "mcp__polymarket__get_event",
    "mcp__polymarket__get_trades",
    "mcp__polymarket__get_portfolio",
    # Database
    "mcp__db__db_query",
    "mcp__db__db_get_session_state",
    "mcp__db__db_log_prediction",
    "mcp__db__db_resolve_predictions",
    "mcp__db__db_add_watchlist",
    "mcp__db__db_remove_watchlist",
    # Filesystem reads
    "Read",
    "Glob",
    "Grep",
}


def _ask_user(prompt: str) -> bool:
    """Prompt user for yes/no approval."""
    try:
        return input(prompt).strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def _parse_response(response: str, options: list[dict]) -> str:
    """Parse user response -- option number or free text."""
    try:
        idx = int(response) - 1
        if 0 <= idx < len(options):
            return options[idx]["label"]
    except ValueError:
        pass
    return response


def _allow(input_data: dict) -> PermissionResultAllow:
    return PermissionResultAllow(updated_input=input_data)


def _deny(message: str, interrupt: bool = False) -> PermissionResultDeny:
    return PermissionResultDeny(message=message, interrupt=interrupt)


def create_permission_handler(
    workspace_path: str,
    permissions: PermissionConfig,
    trading_config: TradingConfig,
):
    """Return an async permission callback bound to config via closure."""

    async def handler(
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Always allow read tools
        if tool_name in _READ_TOOLS:
            return _allow(input_data)

        # -- AskUserQuestion: present questions, collect answers --
        if tool_name == "AskUserQuestion":
            answers: dict[str, str] = {}
            for q in input_data.get("questions", []):
                print(f"\n{q.get('header', '')}: {q['question']}")
                for i, opt in enumerate(q.get("options", [])):
                    print(f"  {i + 1}. {opt['label']} -- {opt.get('description', '')}")
                print("  (Enter number, or type your own answer)")
                try:
                    response = input("Your choice: ").strip()
                except (EOFError, KeyboardInterrupt):
                    response = ""
                answers[q["question"]] = _parse_response(response, q.get("options", []))
            return PermissionResultAllow(
                updated_input={"questions": input_data.get("questions", []), "answers": answers}
            )

        # -- place_order: enforce trading limits (both platforms) --
        if tool_name == "mcp__kalshi__place_order":
            count = input_data.get("count", 0)
            yes_price = input_data.get("yes_price", 0) or 0
            no_price = input_data.get("no_price", 0) or 0
            price = max(yes_price, no_price)
            cost_usd = (count * price) / 100

            if count > trading_config.max_order_count:
                return _deny(
                    f"Order count {count} exceeds max {trading_config.max_order_count} contracts"
                )
            if cost_usd > trading_config.max_position_usd:
                return _deny(
                    f"Position cost ${cost_usd:.2f} exceeds max "
                    f"${trading_config.max_position_usd:.2f}"
                )

            ticker = input_data.get("ticker", "?")
            action = input_data.get("action", "?")
            side = input_data.get("side", "?")
            order_type = input_data.get("order_type", "limit")

            print(f"\n{'=' * 50}")
            print(f"  TRADE: {action.upper()} {count}x {side.upper()} on {ticker}")
            print(f"  Type: {order_type}  |  Price: {price}c  |  Cost: ${cost_usd:.2f}")
            print(f"{'=' * 50}")

            if _ask_user("Approve this trade? (y/n): "):
                return _allow(input_data)
            return _deny("User rejected trade")

        if tool_name == "mcp__polymarket__place_order":
            price = float(input_data.get("price", "0"))
            quantity = input_data.get("quantity", 0)
            cost_usd = quantity * price

            if cost_usd > trading_config.polymarket_max_position_usd:
                return _deny(
                    f"Position cost ${cost_usd:.2f} exceeds Polymarket max "
                    f"${trading_config.polymarket_max_position_usd:.2f}"
                )

            slug = input_data.get("slug", "?")
            intent = input_data.get("intent", "?")
            order_type = input_data.get("order_type", "LIMIT")

            print(f"\n{'=' * 50}")
            print(f"  POLYMARKET: {intent} {quantity}x on {slug}")
            print(f"  Type: {order_type}  |  Price: ${price:.2f}  |  Cost: ${cost_usd:.2f}")
            print(f"{'=' * 50}")

            if _ask_user("Approve this trade? (y/n): "):
                return _allow(input_data)
            return _deny("User rejected Polymarket trade")

        # -- cancel_order: approval (both platforms) --
        if tool_name in ("mcp__kalshi__cancel_order", "mcp__polymarket__cancel_order"):
            exchange = "Polymarket" if "polymarket" in tool_name else "Kalshi"
            order_id = input_data.get("order_id", "?")
            print(f"\n{exchange} cancel order: {order_id}")
            if _ask_user("Approve cancellation? (y/n): "):
                return _allow(input_data)
            return _deny(f"User rejected {exchange} cancellation")

        # -- Bash: restrict to workspace writable directories --
        if tool_name == "Bash":
            command = input_data.get("command", "")
            abs_workspace = os.path.abspath(workspace_path)
            dangerous = ["/app", "/etc", "/usr", "/root", "/home"]
            for d in dangerous:
                if d in command and "pip" not in command:
                    return _deny(f"Bash access restricted to {abs_workspace}")
            return _allow(input_data)

        # -- Write / Edit: check path against patterns --
        if tool_name in ("Write", "Edit"):
            file_path = input_data.get("file_path", "")
            rel_path = os.path.relpath(file_path, workspace_path)

            for pat in permissions.deny_patterns:
                if rel_path.startswith(pat) or pat in rel_path:
                    return _deny(f"Write denied: {rel_path} matches deny pattern '{pat}'")

            for pat in permissions.writable_patterns:
                if rel_path.startswith(pat):
                    return _allow(input_data)

            return _deny(f"Write denied: {rel_path} not in writable directories")

        # Default: auto-approve
        return _allow(input_data)

    return handler
