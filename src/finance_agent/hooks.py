"""Audit hooks -- recommendation counting and KB versioning."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import HookContext, HookEvent, HookInput, HookJSONOutput

from .kb_versioning import commit_kb

logger = logging.getLogger(__name__)

_EMPTY: HookJSONOutput = {}  # type: ignore[assignment]
# Container filesystem contract — agent cannot write to these (kernel-enforced :ro mount)
_PROTECTED_PREFIXES = ("/workspace/data/", "/workspace/scripts/")


def _is_tool_error(response: Any) -> bool:
    """Check if an MCP tool response contains an error."""
    if not response:
        return False
    try:
        # MCP tool responses: {"content": [{"type": "text", "text": "..."}]}
        if isinstance(response, dict):
            for item in response.get("content", []):
                if isinstance(item, dict) and item.get("type") == "text":
                    parsed = json.loads(item["text"])
                    if isinstance(parsed, dict) and "error" in parsed:
                        return True
        elif isinstance(response, str) and '"error"' in response:
            return True
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return False


def create_audit_hooks(
    on_recommendation: Callable[[], None] | None = None,
) -> dict[HookEvent, list[HookMatcher]]:
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
        input_data: HookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        # Check tool_response for errors before counting
        data: dict[str, Any] = input_data  # type: ignore[assignment]
        response = data.get("tool_response")
        if _is_tool_error(response):
            logger.warning("recommend_trade returned an error, not counting")
            return _EMPTY
        nonlocal rec_count
        rec_count += 1
        logger.info("Recommendation #%d recorded", rec_count)
        if on_recommendation:
            on_recommendation()
        return _EMPTY

    async def commit_kb_if_written(
        input_data: HookInput, _tool_use_id: str | None, _context: HookContext
    ) -> HookJSONOutput:
        """Auto-commit knowledge_base.md after agent writes to it."""
        data: dict[str, Any] = input_data  # type: ignore[assignment]
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        is_kb_write = False
        if tool_name in ("Write", "Edit"):
            file_path = tool_input.get("file_path", "")
            is_kb_write = file_path.endswith("knowledge_base.md")
        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            is_kb_write = "knowledge_base.md" in command and any(
                op in command for op in (">>", " > ", "tee ", "mv ", "cp ", "sed ")
            )

        if is_kb_write:
            await commit_kb()
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
            HookMatcher(
                hooks=[commit_kb_if_written],
            ),
        ],
    }
