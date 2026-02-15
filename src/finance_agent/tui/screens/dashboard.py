"""Dashboard screen: agent chat (left) + sidebar (right)."""

from __future__ import annotations

from typing import Any, ClassVar

from claude_agent_sdk import ClaudeSDKClient
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button

from ..messages import (
    AgentCostUpdate,
    AgentResponseComplete,
    AskUserQuestionRequest,
    RecommendationCreated,
    RecommendationExecuted,
)
from ..services import TUIServices
from ..widgets.agent_chat import AgentChat
from ..widgets.portfolio_panel import PortfolioPanel
from ..widgets.rec_list import RecList
from ..widgets.status_bar import StatusBar


class DashboardScreen(Screen):
    """Primary screen: agent chat + portfolio/recs sidebar."""

    BINDINGS: ClassVar[list] = [
        ("f2", "app.switch_screen('recommendations')", "Recs"),
        ("f3", "app.switch_screen('portfolio')", "Portfolio"),
        ("f4", "app.switch_screen('signals')", "Signals"),
        ("f5", "app.switch_screen('history')", "History"),
    ]

    def __init__(
        self,
        client: ClaudeSDKClient,
        services: TUIServices,
        startup_msg: str,
        session_id: str,
        profile: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._services = services
        self._startup_msg = startup_msg
        self._session_id = session_id
        self._profile = profile

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-content"):
            yield AgentChat(self._client, self._startup_msg, id="agent-chat")
            with Vertical(id="sidebar"):
                yield PortfolioPanel(id="portfolio-panel")
                yield RecList(id="rec-list")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.session_id = self._session_id
        bar.profile = self._profile

        # Initial data load
        self.set_interval(30, self._poll_state)
        self.run_worker(self._refresh_sidebar())

    async def _refresh_sidebar(self) -> None:
        """Refresh portfolio and rec list from live data."""
        try:
            portfolio = await self._services.get_portfolio()
            self.query_one("#portfolio-panel", PortfolioPanel).update_data(portfolio)
        except Exception:
            pass

        try:
            recs = self._services.get_pending_recs()
            self.query_one("#rec-list", RecList).update_recs(recs)
        except Exception:
            pass

    async def _poll_state(self) -> None:
        """Periodic refresh for external changes."""
        await self._refresh_sidebar()

    # ── Message handlers ──────────────────────────────────────────

    def on_agent_cost_update(self, event: AgentCostUpdate) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.total_cost = event.total_cost_usd

    def on_agent_response_complete(self, event: AgentResponseComplete) -> None:
        self.run_worker(self._refresh_sidebar())

    def on_recommendation_created(self, event: RecommendationCreated) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.rec_count += 1
        recs = self._services.get_pending_recs()
        self.query_one("#rec-list", RecList).update_recs(recs)

    def on_recommendation_executed(self, event: RecommendationExecuted) -> None:
        self.run_worker(self._refresh_sidebar())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Execute/Reject buttons from sidebar rec cards."""
        from ..widgets.confirm_modal import ConfirmModal

        btn_id = event.button.id or ""

        if btn_id.startswith("exec-group-"):
            group_id = btn_id[len("exec-group-") :]
            recs = [r for r in self._services.get_pending_recs() if r.get("group_id") == group_id]
            if recs:
                self.app.push_screen(
                    ConfirmModal(recs),
                    callback=lambda ok: (
                        self.run_worker(self._execute_and_refresh(group_id=group_id))
                        if ok
                        else None
                    ),
                )

        elif btn_id.startswith("exec-"):
            rec_id = int(btn_id[len("exec-") :])
            recs = [r for r in self._services.get_pending_recs() if r["id"] == rec_id]
            if recs:
                self.app.push_screen(
                    ConfirmModal(recs),
                    callback=lambda ok: (
                        self.run_worker(self._execute_and_refresh(rec_ids=[rec_id]))
                        if ok
                        else None
                    ),
                )

        elif btn_id.startswith("reject-"):
            rec_id = int(btn_id[len("reject-") :])
            await self._services.reject_recommendation(rec_id)
            recs = self._services.get_pending_recs()
            self.query_one("#rec-list", RecList).update_recs(recs)

    async def _execute_and_refresh(
        self,
        group_id: str | None = None,
        rec_ids: list[int] | None = None,
    ) -> None:
        await self._services.execute_recommendation_group(group_id=group_id, rec_ids=rec_ids)
        self.post_message(RecommendationExecuted())
        await self._refresh_sidebar()

    def on_ask_user_question_request(self, event: AskUserQuestionRequest) -> None:
        from ..widgets.ask_modal import AskModal

        def handle_result(answers: dict[str, str] | None) -> None:
            if answers is not None:
                event.future.set_result(answers)
            else:
                event.future.set_result({})

        self.app.push_screen(AskModal(event.questions), callback=handle_result)
