"""Custom Textual messages for inter-widget communication."""

from __future__ import annotations

from typing import Any

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


# ── WS-based agent messages (server → TUI) ─────────────────────


class AgentTextReceived(Message):
    """Agent produced text output (from TextBlock)."""

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content


class AgentToolUse(Message):
    """Agent called a tool."""

    def __init__(self, name: str, tool_id: str, input_data: dict[str, Any]) -> None:
        super().__init__()
        self.name = name
        self.tool_id = tool_id
        self.input_data = input_data


class AgentToolResult(Message):
    """Tool returned a result."""

    def __init__(self, tool_id: str, content: str, is_error: bool) -> None:
        super().__init__()
        self.tool_id = tool_id
        self.content = content
        self.is_error = is_error


class AgentResultReceived(Message):
    """Agent turn completed (cost, error status)."""

    def __init__(self, total_cost_usd: float, is_error: bool) -> None:
        super().__init__()
        self.total_cost_usd = total_cost_usd
        self.is_error = is_error


class AskQuestionReceived(Message):
    """Server relayed AskUserQuestion to TUI."""

    def __init__(self, request_id: str, questions: list[dict[str, Any]]) -> None:
        super().__init__()
        self.request_id = request_id
        self.questions = questions


class SessionReset(Message):
    """Session was rotated (after clear or idle)."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id


class SessionLogSaved(Message):
    """Session log was written to disk."""

    def __init__(self, session_id: str, path: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.path = path
