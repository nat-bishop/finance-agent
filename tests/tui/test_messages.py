"""Tests for finance_agent.tui.messages -- custom Textual messages."""

from __future__ import annotations

from finance_agent.tui.messages import (
    AgentCostUpdate,
    AgentResponseComplete,
    AgentResultReceived,
    AgentTextReceived,
    AgentToolResult,
    AgentToolUse,
    AskQuestionReceived,
    RecommendationCreated,
    RecommendationExecuted,
    SessionReset,
)


def test_agent_cost_update():
    msg = AgentCostUpdate(total_cost_usd=1.2345)
    assert msg.total_cost_usd == 1.2345


def test_agent_response_complete():
    msg = AgentResponseComplete()
    assert msg is not None


def test_recommendation_created():
    msg = RecommendationCreated()
    assert msg is not None


def test_recommendation_executed():
    msg = RecommendationExecuted()
    assert msg is not None


def test_ask_question_received():
    questions = [{"question": "Choose one", "options": [{"label": "A"}]}]
    msg = AskQuestionReceived(request_id="abc123", questions=questions)
    assert msg.request_id == "abc123"
    assert msg.questions == questions


def test_agent_text_received():
    msg = AgentTextReceived(content="Hello world")
    assert msg.content == "Hello world"


def test_agent_tool_use():
    msg = AgentToolUse(name="get_market", tool_id="t1", input_data={"market_id": "K-1"})
    assert msg.name == "get_market"
    assert msg.tool_id == "t1"


def test_agent_tool_result():
    msg = AgentToolResult(tool_id="t1", content="result data", is_error=False)
    assert not msg.is_error


def test_agent_result_received():
    msg = AgentResultReceived(total_cost_usd=0.5, is_error=False)
    assert msg.total_cost_usd == 0.5


def test_session_reset():
    msg = SessionReset(session_id="abc123")
    assert msg.session_id == "abc123"
