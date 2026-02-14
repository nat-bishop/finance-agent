"""Entry point — ClaudeSDKClient interactive REPL."""

from __future__ import annotations

import asyncio
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
from .tools import create_db_tools, create_kalshi_tools, create_polymarket_tools


def build_options(
    agent_config: AgentConfig,
    trading_config: TradingConfig,
    kalshi_mcp: dict,
    db_mcp: dict,
    db: AgentDatabase,
    session_id: str,
    polymarket_mcp: dict | None = None,
    workspace: str = "/workspace",
) -> ClaudeAgentOptions:
    """Assemble ClaudeAgentOptions from configs."""
    system_prompt_text = build_system_prompt(trading_config)

    mcp_servers = {"kalshi": kalshi_mcp, "db": db_mcp}
    if polymarket_mcp:
        mcp_servers["polymarket"] = polymarket_mcp

    polymarket_tools = []
    if polymarket_mcp:
        polymarket_tools = [
            "mcp__polymarket__search_markets",
            "mcp__polymarket__get_market_details",
            "mcp__polymarket__get_orderbook",
            "mcp__polymarket__get_event",
            "mcp__polymarket__get_trades",
            "mcp__polymarket__get_portfolio",
            "mcp__polymarket__place_order",
            "mcp__polymarket__cancel_order",
        ]

    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt_text,
        },
        model=agent_config.model,
        cwd=workspace,
        mcp_servers=mcp_servers,
        allowed_tools=[
            # Kalshi MCP tools
            "mcp__kalshi__search_markets",
            "mcp__kalshi__get_market_details",
            "mcp__kalshi__get_orderbook",
            "mcp__kalshi__get_event",
            "mcp__kalshi__get_price_history",
            "mcp__kalshi__get_recent_trades",
            "mcp__kalshi__get_portfolio",
            "mcp__kalshi__get_open_orders",
            "mcp__kalshi__place_order",
            "mcp__kalshi__cancel_order",
            # Polymarket MCP tools (conditional)
            *polymarket_tools,
            # Database MCP tools
            "mcp__db__db_query",
            "mcp__db__db_log_prediction",
            "mcp__db__db_resolve_predictions",
            "mcp__db__db_get_session_state",
            "mcp__db__db_add_watchlist",
            "mcp__db__db_remove_watchlist",
            # Filesystem tools (built-in)
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            # User interaction
            "AskUserQuestion",
        ],
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

    # Initialize database
    db = AgentDatabase(trading_config.db_path)
    backup_result = db.backup_if_needed(
        trading_config.backup_dir,
        max_age_hours=trading_config.backup_max_age_hours,
    )
    if backup_result:
        print(f"DB backup: {backup_result}")

    session_id = db.create_session(profile=agent_config.profile)

    # Clear session scratch file
    session_log = Path("/workspace/data/session.log")
    session_log.parent.mkdir(parents=True, exist_ok=True)
    session_log.write_text("", encoding="utf-8")

    kalshi_mcp = create_sdk_mcp_server(
        name="kalshi",
        version="1.0.0",
        tools=create_kalshi_tools(kalshi, trading_config),
    )

    db_mcp = create_sdk_mcp_server(
        name="db",
        version="1.0.0",
        tools=create_db_tools(db),
    )

    polymarket_mcp = None
    if trading_config.polymarket_enabled and trading_config.polymarket_key_id:
        pm_client = PolymarketAPIClient(trading_config)
        polymarket_mcp = create_sdk_mcp_server(
            name="polymarket",
            version="1.0.0",
            tools=create_polymarket_tools(pm_client, trading_config),
        )

    options = build_options(
        agent_config,
        trading_config,
        kalshi_mcp,
        db_mcp,
        db,
        session_id,
        polymarket_mcp=polymarket_mcp,
    )

    print("Cross-Platform Prediction Market Arbitrage Agent")
    print(f"Profile: {agent_config.profile}  |  Model: {agent_config.model}")
    print(f"Kalshi: {trading_config.kalshi_env}")
    if polymarket_mcp:
        print("Polymarket: enabled")
    print(f"Max position: ${trading_config.max_position_usd} (Kalshi)")
    if polymarket_mcp:
        print(f"Max position: ${trading_config.polymarket_max_position_usd} (Polymarket)")
    print(f"Max portfolio: ${trading_config.max_portfolio_usd}")
    print(f"Session: {session_id}")
    print("Type 'quit' or 'exit' to stop.\n")

    async with ClaudeSDKClient(options=options) as client:

        async def handle_response():
            """Process and display response messages."""
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

        # Send BEGIN_SESSION to trigger startup protocol
        await client.query("BEGIN_SESSION")
        await handle_response()

        # Interactive loop
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
