"""Entry point -- assembles SDK options, launches TUI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import HookEvent, HookMatcher

from .config import build_system_prompt

# ── Watchlist migration (DB → markdown file) ─────────────────────

_WATCHLIST_PATH = Path("/workspace/data/watchlist.md")


def _init_watchlist(db: Any) -> None:
    """One-time migration: write DB watchlist rows to markdown file."""
    if _WATCHLIST_PATH.exists():
        return
    _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Watchlist\n\n"
        "Markets to monitor across sessions.\n\n"
        "| Ticker | Exchange | Reason | Alert Condition |\n"
        "|--------|----------|--------|-----------------|\n"
    )
    rows = db.query("SELECT ticker, exchange, reason, alert_condition FROM watchlist")
    row_lines = "".join(
        f"| {r['ticker']} | {r['exchange']} | {r.get('reason') or ''} "
        f"| {r.get('alert_condition') or ''} |\n"
        for r in rows
    )
    _WATCHLIST_PATH.write_text(header + row_lines, encoding="utf-8")


# ── Build SDK options ─────────────────────────────────────────────


def build_options(
    agent_config: Any,
    trading_config: Any,
    mcp_servers: dict,
    can_use_tool: Callable[..., Any],
    hooks: dict[HookEvent, list[HookMatcher]],
    workspace: str = "/workspace",
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": build_system_prompt(trading_config),
        },
        model=agent_config.model,
        cwd=workspace,
        mcp_servers=mcp_servers,
        permission_mode="acceptEdits",
        can_use_tool=can_use_tool,
        hooks=hooks,
        max_budget_usd=agent_config.max_budget_usd,
        sandbox={"enabled": True, "autoAllowBashIfSandboxed": True},
    )


def main() -> None:
    from .tui.app import FinanceApp

    app = FinanceApp()
    app.run()


if __name__ == "__main__":
    main()
