"""Permission handler — gates writes, enforces trading limits, handles user interaction."""

from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .config import PermissionConfig, TradingConfig


def create_permission_handler(
    workspace_path: str,
    permissions: PermissionConfig,
    trading_config: TradingConfig,
):
    """Return an async permission callback bound to config via closure.

    Rules:
    - Read-only Kalshi tools: always allow
    - DB read tools: always allow
    - place_order: validate position size, contract count
    - cancel_order: always allow
    - AskUserQuestion: present questions, collect answers
    - Bash: allow only within /workspace writable dirs
    - Write/Edit: allow in writable_patterns, deny in deny_patterns
    - Read/Glob/Grep: always allow
    """

    read_tools = {
        "mcp__kalshi__search_markets",
        "mcp__kalshi__get_market_details",
        "mcp__kalshi__get_orderbook",
        "mcp__kalshi__get_event",
        "mcp__kalshi__get_price_history",
        "mcp__kalshi__get_recent_trades",
        "mcp__kalshi__get_portfolio",
        "mcp__kalshi__get_open_orders",
        # Database reads
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

    def _parse_response(response: str, options: list[dict]) -> str:
        """Parse user response — option number or free text."""
        try:
            idx = int(response) - 1
            if 0 <= idx < len(options):
                return options[idx]["label"]
        except ValueError:
            pass
        return response

    async def handler(
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Always allow read tools
        if tool_name in read_tools:
            return PermissionResultAllow(updated_input=input_data)

        # ── AskUserQuestion: present questions, collect answers ──
        if tool_name == "AskUserQuestion":
            answers: dict[str, str] = {}
            for q in input_data.get("questions", []):
                print(f"\n{q.get('header', '')}: {q['question']}")
                for i, opt in enumerate(q.get("options", [])):
                    print(f"  {i + 1}. {opt['label']} — {opt.get('description', '')}")
                print("  (Enter number, or type your own answer)")
                try:
                    response = input("Your choice: ").strip()
                except (EOFError, KeyboardInterrupt):
                    response = ""
                answers[q["question"]] = _parse_response(response, q.get("options", []))
            return PermissionResultAllow(
                updated_input={
                    "questions": input_data.get("questions", []),
                    "answers": answers,
                }
            )

        def _ask_user(prompt: str) -> bool:
            """Prompt user for yes/no approval."""
            try:
                response = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                response = "n"
            return response.lower() == "y"

        # ── place_order: enforce trading limits ─────────────────────
        if tool_name == "mcp__kalshi__place_order":
            count = input_data.get("count", 0)
            yes_price = input_data.get("yes_price", 0) or 0
            no_price = input_data.get("no_price", 0) or 0
            price = max(yes_price, no_price)

            # Contract count check
            if count > trading_config.max_order_count:
                return PermissionResultDeny(
                    message=(
                        f"Order count {count} exceeds max "
                        f"{trading_config.max_order_count} contracts"
                    ),
                    interrupt=False,
                )

            # Position size check (price in cents, so divide by 100)
            cost_usd = (count * price) / 100
            if cost_usd > trading_config.max_position_usd:
                return PermissionResultDeny(
                    message=(
                        f"Position cost ${cost_usd:.2f} exceeds max "
                        f"${trading_config.max_position_usd:.2f}"
                    ),
                    interrupt=False,
                )

            # Show formatted trade summary and ask for approval
            ticker = input_data.get("ticker", "?")
            action = input_data.get("action", "?")
            side = input_data.get("side", "?")
            order_type = input_data.get("order_type", "limit")

            print(f"\n{'=' * 50}")
            print(f"  TRADE: {action.upper()} {count}x {side.upper()} on {ticker}")
            print(f"  Type: {order_type}  |  Price: {price}¢  |  Cost: ${cost_usd:.2f}")
            print(f"{'=' * 50}")

            if _ask_user("Approve this trade? (y/n): "):
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(message="User rejected trade")

        # ── cancel_order: approval ────────────────────────────────
        if tool_name == "mcp__kalshi__cancel_order":
            order_id = input_data.get("order_id", "?")
            print(f"\nCancel order: {order_id}")
            if _ask_user("Approve cancellation? (y/n): "):
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(message="User rejected cancellation")

        # ── Bash: restrict to workspace writable directories ────────
        if tool_name == "Bash":
            command = input_data.get("command", "")
            abs_workspace = os.path.abspath(workspace_path)
            dangerous = ["/app", "/etc", "/usr", "/root", "/home"]
            for d in dangerous:
                if d in command and "pip" not in command:
                    return PermissionResultDeny(
                        message=f"Bash access restricted to {abs_workspace}",
                        interrupt=False,
                    )
            return PermissionResultAllow(updated_input=input_data)

        # ── Write / Edit: check path against patterns ───────────────
        if tool_name in ("Write", "Edit"):
            file_path = input_data.get("file_path", "")
            rel_path = os.path.relpath(file_path, workspace_path)

            # Deny patterns take precedence
            for pat in permissions.deny_patterns:
                if rel_path.startswith(pat) or pat in rel_path:
                    return PermissionResultDeny(
                        message=f"Write denied: {rel_path} matches deny pattern '{pat}'",
                        interrupt=False,
                    )

            # Check writable patterns
            for pat in permissions.writable_patterns:
                if rel_path.startswith(pat):
                    return PermissionResultAllow(updated_input=input_data)

            # Not in any writable pattern — deny
            return PermissionResultDeny(
                message=f"Write denied: {rel_path} not in writable directories",
                interrupt=False,
            )

        # Default: auto-approve (hooks handle deny/allow for most tools)
        return PermissionResultAllow(updated_input=input_data)

    return handler
