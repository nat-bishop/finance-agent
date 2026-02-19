"""Tests for finance_agent.hooks -- audit hooks and KB versioning."""

from __future__ import annotations

from finance_agent.hooks import create_audit_hooks


def _hook(hooks, event, idx=0):
    """Extract the first hook function from a HookMatcher."""
    return hooks[event][idx].hooks[0]


# ── auto_approve ─────────────────────────────────────────────────


async def test_auto_approve_allows_regular_tool():
    pre = _hook(create_audit_hooks(), "PreToolUse")
    result = await pre({"tool_name": "mcp__markets__get_market", "tool_input": {}}, "tid-1", None)
    assert result != {}
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "updatedInput" not in result["hookSpecificOutput"]


async def test_auto_approve_skips_ask_user():
    pre = _hook(create_audit_hooks(), "PreToolUse")
    result = await pre({"tool_name": "AskUserQuestion", "tool_input": {}}, "tid-1", None)
    assert result == {}


async def test_auto_approve_denies_write_to_protected_path():
    pre = _hook(create_audit_hooks(), "PreToolUse")
    result = await pre(
        {"tool_name": "Write", "tool_input": {"file_path": "/workspace/data/agent.db"}},
        "tid-1",
        None,
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "/workspace/analysis/" in result["hookSpecificOutput"]["permissionDecisionReason"]


async def test_auto_approve_allows_write_to_analysis():
    pre = _hook(create_audit_hooks(), "PreToolUse")
    result = await pre(
        {"tool_name": "Write", "tool_input": {"file_path": "/workspace/analysis/notes.md"}},
        "tid-1",
        None,
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


async def test_auto_approve_denies_edit_to_scripts():
    pre = _hook(create_audit_hooks(), "PreToolUse")
    result = await pre(
        {"tool_name": "Edit", "tool_input": {"file_path": "/workspace/scripts/db_utils.py"}},
        "tid-1",
        None,
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


# ── audit_recommendation ─────────────────────────────────────────


async def test_audit_recommendation_calls_callback():
    calls = []
    hooks = create_audit_hooks(on_recommendation=lambda: calls.append(1))
    post = _hook(hooks, "PostToolUse")
    for _ in range(3):
        await post({}, None, None)
    assert len(calls) == 3


# ── Hook structure ───────────────────────────────────────────────


def test_hook_structure_keys():
    hooks = create_audit_hooks()
    assert "PreToolUse" in hooks
    assert "PostToolUse" in hooks
    assert "Stop" not in hooks


def test_post_tool_use_matcher():
    hooks = create_audit_hooks()
    assert hooks["PostToolUse"][0].matcher == "mcp__db__recommend_trade"


# ── on_recommendation callback ───────────────────────────────────


async def test_on_recommendation_callback():
    calls = []
    hooks = create_audit_hooks(on_recommendation=lambda: calls.append(1))
    post = _hook(hooks, "PostToolUse")
    await post({}, None, None)
    await post({}, None, None)
    assert len(calls) == 2
