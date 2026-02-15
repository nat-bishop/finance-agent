"""Entry point -- ClaudeSDKClient interactive REPL."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
)

from .config import AgentConfig, TradingConfig, build_system_prompt, load_configs
from .database import AgentDatabase
from .hooks import create_audit_hooks
from .kalshi_client import KalshiAPIClient
from .permissions import create_permission_handler
from .polymarket_client import PolymarketAPIClient
from .tools import create_db_tools, create_market_tools

_BUILTIN_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "AskUserQuestion"]


def _mcp_tool_names(server_key: str, tools: list) -> list[str]:
    return [f"mcp__{server_key}__{t.name}" for t in tools]


def build_options(
    agent_config: AgentConfig,
    trading_config: TradingConfig,
    mcp_servers: dict,
    mcp_tools: dict[str, list],
    db: AgentDatabase,
    session_id: str,
    workspace: str = "/workspace",
) -> ClaudeAgentOptions:
    allowed = list(_BUILTIN_TOOLS)
    for key, tools in mcp_tools.items():
        allowed.extend(_mcp_tool_names(key, tools))

    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": build_system_prompt(trading_config),
        },
        model=agent_config.model,
        cwd=workspace,
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        can_use_tool=create_permission_handler(
            workspace_path=workspace,
            permissions=agent_config.permissions,
            trading_config=trading_config,
        ),
        hooks=create_audit_hooks(db=db, session_id=session_id),
        max_budget_usd=agent_config.max_budget_usd,
        permission_mode=agent_config.permission_mode,
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

    # Clear session scratch file
    session_log = Path("/workspace/data/session.log")
    session_log.parent.mkdir(parents=True, exist_ok=True)
    session_log.write_text("", encoding="utf-8")

    polymarket_enabled = trading_config.polymarket_enabled and bool(
        trading_config.polymarket_key_id
    )
    pm_client = PolymarketAPIClient(trading_config) if polymarket_enabled else None

    mcp_tools = {
        "markets": create_market_tools(kalshi, pm_client, trading_config),
        "db": create_db_tools(db),
    }
    mcp_servers = {
        key: create_sdk_mcp_server(name=key, version="1.0.0", tools=tools)
        for key, tools in mcp_tools.items()
    }

    options = build_options(agent_config, trading_config, mcp_servers, mcp_tools, db, session_id)

    # Startup banner
    print("Cross-Platform Prediction Market Arbitrage Agent")
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
