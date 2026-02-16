"""Tests for finance_agent.hooks -- audit hooks and session lifecycle."""

from __future__ import annotations

from unittest.mock import patch

from helpers import get_row

from finance_agent.hooks import create_audit_hooks
from finance_agent.models import Session

# ── auto_approve ─────────────────────────────────────────────────


async def test_auto_approve_allows_regular_tool(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    pre_hook = hooks["PreToolUse"][0].hooks[0]
    result = await pre_hook({"tool_name": "mcp__markets__get_market"}, "tid-1", None)
    assert result != {}
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"


async def test_auto_approve_skips_ask_user(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    pre_hook = hooks["PreToolUse"][0].hooks[0]
    result = await pre_hook({"tool_name": "AskUserQuestion"}, "tid-1", None)
    assert result == {}


# ── audit_recommendation ─────────────────────────────────────────


async def test_audit_recommendation_increments_count(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    post_hook = hooks["PostToolUse"][0].hooks[0]
    # Call three times
    await post_hook({}, None, None)
    await post_hook({}, None, None)
    await post_hook({}, None, None)

    # Verify via session_end which writes rec_count to DB
    stop_hook = hooks["Stop"][0].hooks[0]
    await stop_hook({}, None, None)

    row = get_row(db, Session, session_id)
    assert row["recommendations_made"] == 3


# ── session_end ──────────────────────────────────────────────────


async def test_session_end_writes_db(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    stop_hook = hooks["Stop"][0].hooks[0]
    await stop_hook({}, None, None)

    row = get_row(db, Session, session_id)
    assert row["ended_at"] is not None
    assert "Duration:" in row["summary"]
    assert "Recommendations:" in row["summary"]


async def test_session_end_returns_watchlist_reminder(db, session_id):
    hooks = create_audit_hooks(db, session_id)
    stop_hook = hooks["Stop"][0].hooks[0]
    result = await stop_hook({}, None, None)
    assert "watchlist" in result["systemMessage"].lower()


async def test_session_end_duration_in_summary(db, session_id):
    with patch("finance_agent.hooks.time") as mock_time:
        # First call: session_start in create_audit_hooks
        # Second call: in session_end
        mock_time.time.side_effect = [1000.0, 1060.0]
        hooks = create_audit_hooks(db, session_id)
        stop_hook = hooks["Stop"][0].hooks[0]
        await stop_hook({}, None, None)

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
    matcher = hooks["PostToolUse"][0]
    assert matcher.matcher == "mcp__db__recommend_trade"


# ── on_recommendation callback ───────────────────────────────────


async def test_on_recommendation_callback(db, session_id):
    calls = []
    hooks = create_audit_hooks(db, session_id, on_recommendation=lambda: calls.append(1))
    post_hook = hooks["PostToolUse"][0].hooks[0]
    await post_hook({}, None, None)
    await post_hook({}, None, None)
    assert len(calls) == 2
