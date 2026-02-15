"""Audit hooks -- recommendation counting + session lifecycle."""

from __future__ import annotations

import time
from typing import Any, cast

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookContext, HookEvent, HookInput, HookJSONOutput

from .database import AgentDatabase


def _allow() -> HookJSONOutput:
    return cast(
        HookJSONOutput,
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        },
    )


def create_audit_hooks(
    db: AgentDatabase,
    session_id: str,
) -> dict[HookEvent, list[HookMatcher]]:
    session_start = time.time()
    rec_count = 0

    async def auto_approve(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        """Auto-approve all tools except AskUserQuestion (handled by canUseTool)."""
        data = cast(dict[str, Any], input_data)
        if data.get("tool_name") == "AskUserQuestion":
            return cast(HookJSONOutput, {})  # No decision — falls through to canUseTool
        return _allow()

    async def audit_recommendation(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        nonlocal rec_count
        rec_count += 1
        return cast(HookJSONOutput, {})

    async def session_end(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        duration = time.time() - session_start
        db.end_session(
            session_id=session_id,
            summary=f"Duration: {duration:.0f}s | Recommendations: {rec_count}",
            recommendations_made=rec_count,
        )
        return cast(
            HookJSONOutput,
            {
                "systemMessage": (
                    "Update /workspace/data/watchlist.md with any markets "
                    "to track next session before stopping."
                )
            },
        )

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
