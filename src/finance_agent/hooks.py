"""Audit hooks -- recommendation counting + session lifecycle."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookContext, HookEvent, HookInput, HookJSONOutput

from .database import AgentDatabase

logger = logging.getLogger(__name__)

_EMPTY: HookJSONOutput = {}  # type: ignore[assignment]
# Container filesystem contract — agent cannot write to these (kernel-enforced :ro mount)
_PROTECTED_PREFIXES = ("/workspace/data/", "/workspace/scripts/")


def create_audit_hooks(
    db: AgentDatabase,
    session_id: str,
    on_recommendation: Callable[[], None] | None = None,
) -> dict[HookEvent, list[HookMatcher]]:
    session_start = time.time()
    rec_count = 0

    async def auto_approve(
        input_data: HookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        """Auto-approve tools, deny Write/Edit to read-only paths."""
        data: dict[str, Any] = input_data  # type: ignore[assignment]
        tool_name = data.get("tool_name", "")

        if tool_name == "AskUserQuestion":
            return _EMPTY

        # Block Write/Edit to read-only paths with helpful message
        if tool_name in ("Write", "Edit"):
            tool_input = data.get("tool_input", {})
            file_path = tool_input.get("file_path", "")
            if any(file_path.startswith(p) for p in _PROTECTED_PREFIXES):
                return {  # type: ignore[return-value]
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            f"{file_path} is read-only. "
                            "Write files to /workspace/analysis/ instead. "
                            "Use MCP tools to interact with the database."
                        ),
                    }
                }

        return {  # type: ignore[return-value]
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

    async def audit_recommendation(
        _input_data: HookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        nonlocal rec_count
        rec_count += 1
        logger.info("Recommendation #%d recorded", rec_count)
        if on_recommendation:
            on_recommendation()
        return _EMPTY

    async def session_end(
        _input_data: HookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        duration = time.time() - session_start
        logger.info("Session ending: %ds, %d recommendations", int(duration), rec_count)
        db.end_session(
            session_id=session_id,
            summary=f"Duration: {duration:.0f}s | Recommendations: {rec_count}",
            recommendations_made=rec_count,
        )
        return _EMPTY

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
