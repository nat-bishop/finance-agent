"""Audit hooks -- recommendation counting + session lifecycle."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookContext, HookEvent, HookInput, HookJSONOutput

from .database import AgentDatabase

_ALLOW: HookJSONOutput = {  # type: ignore[assignment]
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    }
}
_EMPTY: HookJSONOutput = {}  # type: ignore[assignment]


def create_audit_hooks(
    db: AgentDatabase,
    session_id: str,
    on_recommendation: Callable[[], None] | None = None,
) -> dict[HookEvent, list[HookMatcher]]:
    session_start = time.time()
    rec_count = 0

    async def auto_approve(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        """Auto-approve all tools except AskUserQuestion (handled by canUseTool)."""
        data: dict[str, Any] = input_data  # type: ignore[assignment]
        return _EMPTY if data.get("tool_name") == "AskUserQuestion" else _ALLOW

    async def audit_recommendation(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        nonlocal rec_count
        rec_count += 1
        if on_recommendation:
            on_recommendation()
        return _EMPTY

    async def session_end(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        duration = time.time() - session_start
        db.end_session(
            session_id=session_id,
            summary=f"Duration: {duration:.0f}s | Recommendations: {rec_count}",
            recommendations_made=rec_count,
        )
        return {  # type: ignore[return-value]
            "systemMessage": (
                "Update /workspace/data/watchlist.md with any markets "
                "to track next session before stopping."
            )
        }

    return {
        "PreToolUse": [
            HookMatcher(hooks=[auto_approve]),
        ],
        "PostToolUse": [
            HookMatcher(
                matcher="mcp__db__recommend_trade",
                hooks=[audit_recommendation],
            ),
        ],
        "Stop": [
            HookMatcher(hooks=[session_end]),
        ],
    }
