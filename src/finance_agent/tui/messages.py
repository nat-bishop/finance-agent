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


class RecommendationCreated(Message):
    """A new recommendation was logged by the agent."""


class RecommendationExecuted(Message):
    """A recommendation was executed through the TUI."""


class ExecutionProgress(Message):
    """Real-time status update during leg-in execution."""

    def __init__(self, group_id: int, status: str, leg_id: int | None = None) -> None:
        super().__init__()
        self.group_id = group_id
        self.status = status
        self.leg_id = leg_id


class FillReceived(Message):
    """WebSocket fill notification for an order."""

    def __init__(
        self,
        order_id: str,
        fill_price_cents: int,
        fill_quantity: int,
        exchange: str,
    ) -> None:
        super().__init__()
        self.order_id = order_id
        self.fill_price_cents = fill_price_cents
        self.fill_quantity = fill_quantity
        self.exchange = exchange


class AskUserQuestionRequest(Message):
    """Agent needs user input via AskUserQuestion tool."""

    def __init__(self, questions: list[dict], future: asyncio.Future) -> None:
        super().__init__()
        self.questions = questions
        self.future = future
