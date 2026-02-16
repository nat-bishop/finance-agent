"""Tests for finance_agent.tui.messages -- custom Textual messages."""

from __future__ import annotations

import asyncio

from finance_agent.tui.messages import (
    AgentCostUpdate,
    AgentResponseComplete,
    AskUserQuestionRequest,
    RecommendationCreated,
    RecommendationExecuted,
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


def test_ask_user_question_request():
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    questions = [{"question": "Choose one", "options": [{"label": "A"}]}]
    msg = AskUserQuestionRequest(questions=questions, future=future)
    assert msg.questions == questions
    assert msg.future is future
    loop.close()
