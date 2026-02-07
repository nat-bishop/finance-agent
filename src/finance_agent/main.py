"""Entry point — ClaudeSDKClient interactive REPL."""

from __future__ import annotations

import asyncio
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk import create_sdk_mcp_server

from .config import AgentConfig, TradingConfig, build_system_prompt, load_configs
from .hooks import create_audit_hooks
from .kalshi_client import KalshiAPIClient
from .permissions import create_permission_handler
from .tools import create_kalshi_tools


def build_options(
    agent_config: AgentConfig,
    trading_config: TradingConfig,
    kalshi_mcp: dict,
    workspace: str = "/workspace",
) -> ClaudeAgentOptions:
    """Assemble ClaudeAgentOptions from configs."""
    system_prompt_text = build_system_prompt(trading_config)

    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt_text,
        },
        model=agent_config.model,
        cwd=workspace,
        mcp_servers={"kalshi": kalshi_mcp},
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
            # Filesystem tools (built-in)
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
        ],
        can_use_tool=create_permission_handler(
            workspace_path=workspace,
            permissions=agent_config.permissions,
            trading_config=trading_config,
        ),
        hooks=create_audit_hooks(Path(workspace) / "trade_journal"),
        max_budget_usd=agent_config.max_budget_usd,
        permission_mode=agent_config.permission_mode,
        sandbox={"enabled": True, "autoAllowBashIfSandboxed": True},
    )


async def run_repl() -> None:
    """Run the interactive REPL."""
    agent_config, trading_config = load_configs()
    kalshi = KalshiAPIClient(trading_config)

    kalshi_mcp = create_sdk_mcp_server(
        name="kalshi",
        version="1.0.0",
        tools=create_kalshi_tools(kalshi, trading_config),
    )

    options = build_options(agent_config, trading_config, kalshi_mcp)

    print("Kalshi Trading Agent")
    print(f"Profile: {agent_config.profile}  |  Model: {agent_config.model}")
    print(f"Environment: {trading_config.kalshi_env}")
    print(f"Max position: ${trading_config.max_position_usd}")
    print(f"Max portfolio: ${trading_config.max_portfolio_usd}")
    print("Type 'quit' or 'exit' to stop.\n")

    session_id = None

    async with ClaudeSDKClient(options=options) as client:
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

            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            print(block.text)
                elif isinstance(msg, ResultMessage):
                    session_id = msg.session_id
                    if msg.total_cost_usd is not None:
                        print(f"  [cost: ${msg.total_cost_usd:.4f}]")
                    if msg.is_error:
                        print(f"  [error: {msg.result}]")

            print()  # blank line between turns


def main() -> None:
    asyncio.run(run_repl())


if __name__ == "__main__":
    main()
