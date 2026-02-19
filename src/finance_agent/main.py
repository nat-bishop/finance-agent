"""Entry point -- assembles SDK options, launches TUI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# TODO(nat): remove once claude-agent-sdk handles rate_limit_event natively  # noqa: TD003
# SDK 0.1.38 parser crashes on unknown message types from the bundled CLI.
import claude_agent_sdk._internal.message_parser as _mp
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import HookEvent, HookMatcher

_original_parse = _mp.parse_message


def _tolerant_parse(data):  # type: ignore[no-untyped-def]
    try:
        return _original_parse(data)
    except _mp.MessageParseError as e:
        if "Unknown message type" in str(e):
            return None
        raise


_mp.parse_message = _tolerant_parse
import claude_agent_sdk.client as _client_mod  # noqa: E402

if hasattr(_client_mod, "parse_message"):
    _client_mod.parse_message = _tolerant_parse

from .config import build_system_prompt  # noqa: E402

# ── Build SDK options ─────────────────────────────────────────────


def build_options(
    agent_config: Any,
    trading_config: Any,
    mcp_servers: dict,
    can_use_tool: Callable[..., Any],
    hooks: dict[HookEvent, list[HookMatcher]],
    workspace: str = "/workspace",
    session_context: str = "",
) -> ClaudeAgentOptions:
    prompt = build_system_prompt(trading_config)
    if session_context:
        prompt += "\n\n" + session_context
    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": prompt,
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
    from .config import load_configs
    from .logging_config import setup_logging
    from .tui.app import FinanceApp

    _, _, trading_config = load_configs()
    setup_logging(log_file=trading_config.log_file or None, console=False)
    app = FinanceApp()
    app.run()


if __name__ == "__main__":
    main()
