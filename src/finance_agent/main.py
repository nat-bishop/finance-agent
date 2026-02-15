"""Entry point -- ClaudeSDKClient interactive REPL."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from .config import build_system_prompt, load_configs
from .database import AgentDatabase
from .hooks import create_audit_hooks
from .kalshi_client import KalshiAPIClient
from .polymarket_client import PolymarketAPIClient
from .tools import create_db_tools, create_market_tools

# ── canUseTool — handles AskUserQuestion ─────────────────────


def _parse_response(response: str, options: list[dict]) -> str:
    try:
        idx = int(response) - 1
        if 0 <= idx < len(options):
            return options[idx]["label"]
    except ValueError:
        pass
    return response


async def _can_use_tool(
    tool_name: str, input_data: dict[str, Any], context: Any
) -> PermissionResultAllow | PermissionResultDeny:
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

    return PermissionResultAllow(updated_input=input_data)


# ── Watchlist migration (DB → markdown file) ─────────────────────

_WATCHLIST_PATH = Path("/workspace/data/watchlist.md")


def _init_watchlist(db: AgentDatabase) -> None:
    """One-time migration: write DB watchlist rows to markdown file."""
    if _WATCHLIST_PATH.exists():
        return
    rows = db.query("SELECT ticker, exchange, reason, alert_condition FROM watchlist")
    _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        _WATCHLIST_PATH.write_text(
            "# Watchlist\n\n"
            "Markets to monitor across sessions.\n\n"
            "| Ticker | Exchange | Reason | Alert Condition |\n"
            "|--------|----------|--------|-----------------|\n",
            encoding="utf-8",
        )
        return
    lines = [
        "# Watchlist\n",
        "\nMarkets to monitor across sessions.\n",
        "\n| Ticker | Exchange | Reason | Alert Condition |",
        "\n|--------|----------|--------|-----------------|",
    ]
    for r in rows:
        reason = r.get("reason") or ""
        alert = r.get("alert_condition") or ""
        lines.append(f"\n| {r['ticker']} | {r['exchange']} | {reason} | {alert} |")
    lines.append("\n")
    _WATCHLIST_PATH.write_text("".join(lines), encoding="utf-8")


# ── Build SDK options ─────────────────────────────────────────────


def build_options(
    agent_config,
    trading_config,
    mcp_servers: dict,
    db: AgentDatabase,
    session_id: str,
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
        can_use_tool=_can_use_tool,
        hooks=create_audit_hooks(db=db, session_id=session_id),
        max_budget_usd=agent_config.max_budget_usd,
        sandbox={"enabled": True, "autoAllowBashIfSandboxed": True},
    )


async def run_repl() -> None:
    """Run the interactive REPL."""
    agent_config, trading_config = load_configs()
    kalshi = KalshiAPIClient(trading_config)

    db = AgentDatabase(trading_config.db_path)
    backup_result = db.backup_if_needed(
        trading_config.backup_dir,
        max_age_hours=trading_config.backup_max_age_hours,
    )
    if backup_result:
        print(f"DB backup: {backup_result}")

    session_id = db.create_session(profile=agent_config.profile)

    # Auto-resolve predictions against settled markets
    resolved = db.auto_resolve_predictions()

    # Build startup context (injected into BEGIN_SESSION, no tool call needed)
    startup_state = db.get_session_state()
    if resolved:
        startup_state["newly_resolved_predictions"] = resolved
    startup_state["watchlist_file"] = str(_WATCHLIST_PATH)

    # Migrate watchlist from DB to markdown file (one-time)
    _init_watchlist(db)

    # Clear session scratch file
    session_log = Path("/workspace/data/session.log")
    session_log.parent.mkdir(parents=True, exist_ok=True)
    session_log.write_text("", encoding="utf-8")

    polymarket_enabled = trading_config.polymarket_enabled and bool(
        trading_config.polymarket_key_id
    )
    pm_client = PolymarketAPIClient(trading_config) if polymarket_enabled else None

    mcp_tools = {
        "markets": create_market_tools(kalshi, pm_client),
        "db": create_db_tools(db, session_id, trading_config.recommendation_ttl_minutes),
    }
    mcp_servers = {
        key: create_sdk_mcp_server(name=key, version="1.0.0", tools=tools)
        for key, tools in mcp_tools.items()
    }

    options = build_options(agent_config, trading_config, mcp_servers, db, session_id)

    # Startup banner
    print("Cross-Platform Prediction Market Analyst")
    print(f"Profile: {agent_config.profile}  |  Model: {agent_config.model}")
    print(f"Kalshi: {trading_config.kalshi_env}")
    if polymarket_enabled:
        print("Polymarket: enabled")
        print(f"Max position: ${trading_config.polymarket_max_position_usd} (Polymarket)")
    print(f"Max position: ${trading_config.kalshi_max_position_usd} (Kalshi)")
    print(f"Max portfolio: ${trading_config.max_portfolio_usd}")
    print(f"Session: {session_id}")
    print("Type 'quit' or 'exit' to stop.\n")

    async with ClaudeSDKClient(options=options) as client:

        async def handle_response():
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            print(block.text)
                elif isinstance(msg, ResultMessage):
                    if msg.total_cost_usd is not None:
                        print(f"  [cost: ${msg.total_cost_usd:.4f}]")
                    if msg.is_error:
                        print(f"  [error: {msg.result}]")
            print()

        # Send BEGIN_SESSION with injected startup context
        startup_msg = f"BEGIN_SESSION\n\n{json.dumps(startup_state, indent=2)}"
        await client.query(startup_msg)
        await handle_response()

        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Goodbye.")
                break

            await client.query(user_input)
            await handle_response()

    db.close()


def main() -> None:
    asyncio.run(run_repl())


if __name__ == "__main__":
    main()
