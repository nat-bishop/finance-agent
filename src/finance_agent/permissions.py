"""Permission handler -- gates writes, enforces trading limits, handles user interaction."""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .config import PermissionConfig, TradingConfig

# Tools that are always auto-approved (reads + DB + filesystem)
_READ_TOOLS = {
    "mcp__markets__search_markets",
    "mcp__markets__get_market",
    "mcp__markets__get_orderbook",
    "mcp__markets__get_event",
    "mcp__markets__get_price_history",
    "mcp__markets__get_trades",
    "mcp__markets__get_portfolio",
    "mcp__markets__get_orders",
    "mcp__db__db_query",
    "mcp__db__db_log_prediction",
    "mcp__db__db_add_watchlist",
    "mcp__db__db_remove_watchlist",
    "Read",
    "Glob",
    "Grep",
}

_DANGEROUS_PATHS = ["/app", "/etc", "/usr", "/root", "/home"]


def _ask_user(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def _approve_or_reject(
    input_data: dict, lines: list[str], prompt: str, reject_msg: str
) -> PermissionResultAllow | PermissionResultDeny:
    print("\n" + "\n".join(lines))
    if _ask_user(prompt):
        return PermissionResultAllow(updated_input=input_data)
    return PermissionResultDeny(message=reject_msg)


def _parse_response(response: str, options: list[dict]) -> str:
    try:
        idx = int(response) - 1
        if 0 <= idx < len(options):
            return options[idx]["label"]
    except ValueError:
        pass
    return response


def create_permission_handler(
    workspace_path: str,
    permissions: PermissionConfig,
    trading_config: TradingConfig,
):
    async def handler(
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name in _READ_TOOLS:
            return PermissionResultAllow(updated_input=input_data)

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

        if tool_name == "mcp__markets__place_order":
            exchange = input_data.get("exchange", "kalshi")
            orders = input_data.get("orders", [])
            max_pos = (
                trading_config.kalshi_max_position_usd
                if exchange == "kalshi"
                else trading_config.polymarket_max_position_usd
            )

            lines = ["=" * 50]
            total_cost = 0.0
            for o in orders:
                price, qty = o.get("price_cents", 0), o.get("quantity", 0)
                cost = (qty * price) / 100
                total_cost += cost
                if qty > trading_config.max_order_count:
                    return PermissionResultDeny(
                        message=f"Order qty {qty} exceeds max {trading_config.max_order_count} contracts"
                    )
                lines.append(
                    f"  {exchange.upper()}: {o.get('action', '?').upper()} "
                    f"{qty}x {o.get('side', '?').upper()} on {o.get('market_id', '?')}"
                )
                lines.append(
                    f"  Type: {o.get('type', 'limit')}  |  Price: {price}c  |  Cost: ${cost:.2f}"
                )

            if total_cost > max_pos:
                return PermissionResultDeny(
                    message=f"Total cost ${total_cost:.2f} exceeds {exchange} max ${max_pos:.2f}"
                )
            lines.append("=" * 50)
            return _approve_or_reject(
                input_data, lines, "Approve this trade? (y/n): ", "User rejected trade"
            )

        if tool_name == "mcp__markets__amend_order":
            lines = [f"Amend order: {input_data.get('order_id', '?')}"]
            if input_data.get("price_cents"):
                lines.append(f"  New price: {input_data['price_cents']}c")
            if input_data.get("quantity"):
                lines.append(f"  New qty: {input_data['quantity']}")
            return _approve_or_reject(
                input_data, lines, "Approve amendment? (y/n): ", "User rejected amendment"
            )

        if tool_name == "mcp__markets__cancel_order":
            exchange = input_data.get("exchange", "?")
            ids = input_data.get("order_ids", [])
            lines = [f"{exchange.upper()} cancel: {len(ids)} order(s)"]
            lines.extend(f"  {oid}" for oid in ids[:5])
            return _approve_or_reject(
                input_data, lines, "Approve cancellation? (y/n): ", "User rejected cancellation"
            )

        if tool_name == "Bash":
            command = input_data.get("command", "")
            abs_workspace = os.path.abspath(workspace_path)
            if any(d in command and "pip" not in command for d in _DANGEROUS_PATHS):
                return PermissionResultDeny(message=f"Bash access restricted to {abs_workspace}")
            return PermissionResultAllow(updated_input=input_data)

        if tool_name in ("Write", "Edit"):
            file_path = input_data.get("file_path", "")
            rel_path = os.path.relpath(file_path, workspace_path)
            for pat in permissions.deny_patterns:
                if rel_path.startswith(pat) or pat in rel_path:
                    return PermissionResultDeny(
                        message=f"Write denied: {rel_path} matches deny pattern '{pat}'"
                    )
            for pat in permissions.writable_patterns:
                if rel_path.startswith(pat):
                    return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(
                message=f"Write denied: {rel_path} not in writable directories"
            )

        return PermissionResultAllow(updated_input=input_data)

    return handler
