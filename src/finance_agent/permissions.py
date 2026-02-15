"""Permission handler -- gates writes, enforces trading limits, handles user interaction."""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .config import PermissionConfig, TradingConfig

# Tools that are always auto-approved (reads + DB + filesystem)
_READ_TOOLS = {
    # Unified market reads
    "mcp__markets__search_markets",
    "mcp__markets__get_market",
    "mcp__markets__get_orderbook",
    "mcp__markets__get_event",
    "mcp__markets__get_price_history",
    "mcp__markets__get_trades",
    "mcp__markets__get_portfolio",
    "mcp__markets__get_orders",
    # Database
    "mcp__db__db_query",
    "mcp__db__db_log_prediction",
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

        # -- place_order: enforce trading limits (unified) --
        if tool_name == "mcp__markets__place_order":
            exchange = input_data.get("exchange", "kalshi")
            orders = input_data.get("orders", [])

            # Per-exchange position limit
            if exchange == "kalshi":
                max_pos = trading_config.kalshi_max_position_usd
            else:
                max_pos = trading_config.polymarket_max_position_usd

            total_cost = 0.0
            for o in orders:
                price = o.get("price_cents", 0)
                qty = o.get("quantity", 0)
                cost = (qty * price) / 100
                total_cost += cost

                if qty > trading_config.max_order_count:
                    return _deny(
                        f"Order qty {qty} exceeds max {trading_config.max_order_count} contracts"
                    )

            if total_cost > max_pos:
                return _deny(f"Total cost ${total_cost:.2f} exceeds {exchange} max ${max_pos:.2f}")

            # Format approval prompt
            print(f"\n{'=' * 50}")
            for o in orders:
                price = o.get("price_cents", 0)
                qty = o.get("quantity", 0)
                cost = (qty * price) / 100
                print(
                    f"  {exchange.upper()}: {o.get('action', '?').upper()} "
                    f"{qty}x {o.get('side', '?').upper()} on {o.get('market_id', '?')}"
                )
                print(
                    f"  Type: {o.get('type', 'limit')}  |  Price: {price}c  |  Cost: ${cost:.2f}"
                )
            print(f"{'=' * 50}")

            if _ask_user("Approve this trade? (y/n): "):
                return _allow(input_data)
            return _deny("User rejected trade")

        # -- amend_order: approval --
        if tool_name == "mcp__markets__amend_order":
            order_id = input_data.get("order_id", "?")
            print(f"\nAmend order: {order_id}")
            if input_data.get("price_cents"):
                print(f"  New price: {input_data['price_cents']}c")
            if input_data.get("quantity"):
                print(f"  New qty: {input_data['quantity']}")
            if _ask_user("Approve amendment? (y/n): "):
                return _allow(input_data)
            return _deny("User rejected amendment")

        # -- cancel_order: approval --
        if tool_name == "mcp__markets__cancel_order":
            exchange = input_data.get("exchange", "?")
            ids = input_data.get("order_ids", [])
            print(f"\n{exchange.upper()} cancel: {len(ids)} order(s)")
            for oid in ids[:5]:
                print(f"  {oid}")
            if _ask_user("Approve cancellation? (y/n): "):
                return _allow(input_data)
            return _deny("User rejected cancellation")

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
