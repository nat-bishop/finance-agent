"""Permission handler — gates writes, enforces trading limits."""

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
    - place_order: validate position size, contract count, require confirmation
    - cancel_order: always allow
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
        "Read",
        "Glob",
        "Grep",
    }

    async def handler(
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Always allow read tools
        if tool_name in read_tools:
            return PermissionResultAllow()

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

            # Validation passed — SDK will still prompt user for confirmation
            # because we are in "default" permission mode.
            return PermissionResultAllow()

        # ── cancel_order: always allow ──────────────────────────────
        if tool_name == "mcp__kalshi__cancel_order":
            return PermissionResultAllow()

        # ── Bash: restrict to workspace writable directories ────────
        if tool_name == "Bash":
            command = input_data.get("command", "")
            # Block commands that escape workspace
            abs_workspace = os.path.abspath(workspace_path)
            # Simple heuristic: disallow cd outside workspace, writing to /app
            dangerous = ["/app", "/etc", "/usr", "/root", "/home"]
            for d in dangerous:
                if d in command and "pip" not in command:
                    return PermissionResultDeny(
                        message=f"Bash access restricted to {abs_workspace}",
                        interrupt=False,
                    )
            return PermissionResultAllow()

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
                    return PermissionResultAllow()

            # Not in any writable pattern — deny
            return PermissionResultDeny(
                message=f"Write denied: {rel_path} not in writable directories",
                interrupt=False,
            )

        # Default: let SDK handle (will prompt user)
        return PermissionResultAllow()

    return handler
