"""Dashboard screen: agent chat (left) + sidebar (right)."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button

from ..messages import (
    AgentCostUpdate,
    AgentResponseComplete,
    AskQuestionReceived,
    RecommendationCreated,
    RecommendationExecuted,
    SessionReset,
)
from ..services import TUIServices
from ..widgets.agent_chat import AgentChat
from ..widgets.portfolio_panel import PortfolioPanel
from ..widgets.rec_list import RecList
from ..widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)


class DashboardScreen(Screen):
    """Primary screen: agent chat + portfolio/recs sidebar."""

    BINDINGS: ClassVar[list] = [
        ("f2", "app.switch_screen('knowledge_base')", "KB"),
        ("f3", "app.switch_screen('recommendations')", "Recs"),
        ("f4", "app.switch_screen('portfolio')", "Portfolio"),
        ("f5", "app.switch_screen('history')", "History"),
        ("f6", "app.switch_screen('performance')", "P&L"),
        ("ctrl+l", "app.clear_chat", "Clear"),
    ]

    def __init__(
        self,
        services: TUIServices,
        session_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._services = services
        self._session_id = session_id

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-content"):
            yield AgentChat(id="agent-chat")
            with Vertical(id="sidebar"):
                yield PortfolioPanel(id="portfolio-panel")
                yield RecList(id="rec-list")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.session_id = self._session_id

        # Initial data load + 30s polling for external changes
        self.set_interval(30, self._refresh_sidebar)
        self.run_worker(self._refresh_sidebar())

    async def _refresh_sidebar(self) -> None:
        """Refresh portfolio, knowledge base, and rec list from live data."""
        try:
            portfolio = await self._services.get_portfolio()
            self.query_one("#portfolio-panel", PortfolioPanel).update_data(portfolio)
        except Exception:
            logger.debug("Failed to refresh portfolio", exc_info=True)

        try:
            groups = self._services.get_pending_groups()
            self.query_one("#rec-list", RecList).update_recs(groups)
            self.query_one("#status-bar", StatusBar).rec_count = len(groups)
        except Exception:
            logger.debug("Failed to refresh rec list", exc_info=True)

    # ── Message handlers ──────────────────────────────────────────

    def on_agent_cost_update(self, event: AgentCostUpdate) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.total_cost = event.total_cost_usd

    def on_agent_response_complete(self, event: AgentResponseComplete) -> None:
        self.run_worker(self._refresh_sidebar())

    def on_recommendation_created(self, event: RecommendationCreated) -> None:
        self.run_worker(self._refresh_sidebar())

    def on_recommendation_executed(self, event: RecommendationExecuted) -> None:
        self.run_worker(self._refresh_sidebar())

    def on_session_reset(self, event: SessionReset) -> None:
        """Handle session rotation from server (clear/idle)."""
        self._session_id = event.session_id
        bar = self.query_one("#status-bar", StatusBar)
        bar.session_id = event.session_id
        bar.total_cost = 0.0

        # Clear chat widget
        self.query_one("#agent-chat", AgentChat).reset()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Execute/Reject buttons from sidebar rec cards."""
        from ..widgets.confirm_modal import ConfirmModal

        btn_id = event.button.id or ""

        if btn_id.startswith("exec-group-"):
            group_id = int(btn_id.removeprefix("exec-group-"))
            group = self._services.db.get_group(group_id)
            if group:

                def on_confirm(ok: bool | None) -> None:
                    if ok:
                        self.run_worker(self._execute_and_refresh(group_id))

                self.app.push_screen(ConfirmModal(group), callback=on_confirm)

        elif btn_id.startswith("reject-group-"):
            await self._services.reject_group(int(btn_id.removeprefix("reject-group-")))
            groups = self._services.get_pending_groups()
            self.query_one("#rec-list", RecList).update_recs(groups)

    async def _execute_and_refresh(self, group_id: int) -> None:
        await self._services.execute_recommendation_group(group_id)
        self.post_message(RecommendationExecuted())
        await self._refresh_sidebar()

    def on_ask_question_received(self, event: AskQuestionReceived) -> None:
        """Handle AskUserQuestion relayed from server via WS."""
        from ..widgets.ask_modal import AskModal

        def _send_answer(answers: dict[str, str] | None) -> None:
            self.run_worker(
                self.app.send_ws(
                    {  # type: ignore[attr-defined]
                        "type": "ask_response",
                        "request_id": event.request_id,
                        "answers": answers or {},
                    }
                )
            )

        self.app.push_screen(
            AskModal(event.questions),
            callback=_send_answer,
        )
