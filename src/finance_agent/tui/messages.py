"""Custom Textual messages for inter-widget communication."""

from __future__ import annotations

import asyncio

from textual.message import Message


class AgentCostUpdate(Message):
    """Agent response included cost info."""

    def __init__(self, total_cost_usd: float) -> None:
        super().__init__()
        self.total_cost_usd = total_cost_usd


class AgentResponseComplete(Message):
    """Agent finished streaming a response."""


class AgentStreaming(Message):
    """Agent started streaming a response."""


class RecommendationCreated(Message):
    """A new recommendation was logged by the agent."""


class RecommendationExecuted(Message):
    """A recommendation was executed through the TUI."""


class AskUserQuestionRequest(Message):
    """Agent needs user input via AskUserQuestion tool."""

    def __init__(self, questions: list[dict], future: asyncio.Future) -> None:
        super().__init__()
        self.questions = questions
        self.future = future
