"""Tests for finance_agent.hooks -- audit hooks and session lifecycle."""

from __future__ import annotations

from unittest.mock import patch

from helpers import get_row

from finance_agent.hooks import create_audit_hooks
from finance_agent.models import Session


def _hook(hooks, event, idx=0):
    """Extract the first hook function from a HookMatcher."""
    return hooks[event][idx].hooks[0]


# ── auto_approve ─────────────────────────────────────────────────


async def test_auto_approve_allows_regular_tool(db, session_id):
    pre = _hook(create_audit_hooks(db, session_id), "PreToolUse")
    result = await pre({"tool_name": "mcp__markets__get_market"}, "tid-1", None)
    assert result != {}
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


async def test_auto_approve_skips_ask_user(db, session_id):
    pre = _hook(create_audit_hooks(db, session_id), "PreToolUse")
    result = await pre({"tool_name": "AskUserQuestion"}, "tid-1", None)
    assert result == {}


async def test_auto_approve_denies_write_to_protected_path(db, session_id):
    pre = _hook(create_audit_hooks(db, session_id), "PreToolUse")
    result = await pre(
        {"tool_name": "Write", "file_path": "/workspace/data/agent.db"}, "tid-1", None
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "/workspace/analysis/" in result["hookSpecificOutput"]["permissionDecisionReason"]


async def test_auto_approve_allows_write_to_analysis(db, session_id):
    pre = _hook(create_audit_hooks(db, session_id), "PreToolUse")
    result = await pre(
        {"tool_name": "Write", "file_path": "/workspace/analysis/notes.md"}, "tid-1", None
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


async def test_auto_approve_denies_edit_to_scripts(db, session_id):
    pre = _hook(create_audit_hooks(db, session_id), "PreToolUse")
    result = await pre(
        {"tool_name": "Edit", "file_path": "/workspace/scripts/db_utils.py"}, "tid-1", None
    )
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


# ── audit_recommendation ─────────────────────────────────────────


async def test_audit_recommendation_increments_count(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    post = _hook(hooks, "PostToolUse")
    for _ in range(3):
        await post({}, None, None)

    # Verify via session_end which writes rec_count to DB
    await _hook(hooks, "Stop")({}, None, None)

    row = get_row(db, Session, session_id)
    assert row["recommendations_made"] == 3


# ── session_end ──────────────────────────────────────────────────


async def test_session_end_writes_db(db, session_id):
    await _hook(create_audit_hooks(db, session_id), "Stop")({}, None, None)

    row = get_row(db, Session, session_id)
    assert row["ended_at"] is not None
    assert "Duration:" in row["summary"]
    assert "Recommendations:" in row["summary"]


async def test_session_end_returns_empty(db, session_id):
    result = await _hook(create_audit_hooks(db, session_id), "Stop")({}, None, None)
    assert result == {}


async def test_session_end_duration_in_summary(db, session_id):
    with patch("finance_agent.hooks.time") as mock_time:
        mock_time.time.side_effect = [1000.0, 1060.0]
        hooks = create_audit_hooks(db, session_id)
        await _hook(hooks, "Stop")({}, None, None)

    row = get_row(db, Session, session_id)
    assert "60s" in row["summary"]


# ── Hook structure ───────────────────────────────────────────────


def test_hook_structure_keys(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    assert "PreToolUse" in hooks
    assert "PostToolUse" in hooks
    assert "Stop" in hooks


def test_post_tool_use_matcher(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    assert hooks["PostToolUse"][0].matcher == "mcp__db__recommend_trade"


# ── on_recommendation callback ───────────────────────────────────


async def test_on_recommendation_callback(db, session_id):
    calls = []
    hooks = create_audit_hooks(db, session_id, on_recommendation=lambda: calls.append(1))
    post = _hook(hooks, "PostToolUse")
    await post({}, None, None)
    await post({}, None, None)
    assert len(calls) == 2
