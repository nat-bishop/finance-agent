"""Full-screen recommendation review and execution."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from ..messages import RecommendationExecuted
from ..services import TUIServices
from ..widgets.confirm_modal import ConfirmModal
from ..widgets.rec_card import RecCard
from ..widgets.status_bar import StatusBar


class RecommendationsScreen(Screen):
    """F2: Full recommendation review with grouped execution."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f3", "app.switch_screen('portfolio')", "Portfolio"),
        ("f4", "app.switch_screen('signals')", "Signals"),
        ("f5", "app.switch_screen('history')", "History"),
        ("escape", "app.switch_screen('dashboard')", "Back"),
    ]

    def __init__(self, services: TUIServices, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services = services

    def compose(self) -> ComposeResult:
        yield Static("[bold]Recommendations[/]", id="recs-title")
        yield VerticalScroll(id="recs-container")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        container = self.query_one("#recs-container", VerticalScroll)

        # Clear existing cards and messages
        for card in container.query(RecCard):
            card.remove()
        for static in container.query(".rec-status-msg"):
            static.remove()

        # Get pending groups
        pending = self._services.get_pending_groups()

        if not pending:
            container.mount(Static("[dim]No pending recommendations[/]", classes="rec-status-msg"))

        for group in pending:
            container.mount(RecCard(group))

        # Show recent non-pending
        recent = self._services.get_recommendations(limit=20)
        non_pending = [g for g in recent if g.get("status") != "pending"]
        if non_pending:
            container.mount(Static("\n[bold]Recent[/]", classes="rec-status-msg"))
            for group in non_pending[:10]:
                status = group.get("status", "?")
                legs = group.get("legs", [])
                leg_summary = ", ".join(
                    f"{lg.get('exchange', '?').upper()}: {lg.get('action', '?').upper()} "
                    f"{lg.get('side', '?').upper()}"
                    for lg in legs[:3]
                )
                container.mount(
                    Static(
                        f"  [{status}] {leg_summary}",
                        classes="rec-status-msg",
                    )
                )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id.startswith("exec-group-"):
            group_id = int(btn_id[len("exec-group-") :])
            group = self._services.db.get_group(group_id)
            if group:
                await self._confirm_and_execute(group)

        elif btn_id.startswith("reject-group-"):
            group_id = int(btn_id[len("reject-group-") :])
            await self._services.reject_group(group_id)
            await self._refresh()

    async def _confirm_and_execute(self, group: dict[str, Any]) -> None:
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self.run_worker(self._do_execute(group["id"]))

        self.app.push_screen(ConfirmModal(group), callback=on_confirm)

    async def _do_execute(self, group_id: int) -> None:
        results = await self._services.execute_recommendation_group(group_id)

        # Show results
        container = self.query_one("#recs-container", VerticalScroll)
        for r in results:
            if r["status"] == "executed":
                container.mount(
                    Static(
                        f"  [green]Executed leg #{r['leg_id']}: "
                        f"order {r.get('order_id', 'N/A')}[/]",
                        classes="rec-status-msg",
                    )
                )
            else:
                container.mount(
                    Static(
                        f"  [red]Failed leg #{r['leg_id']}: {r.get('error', 'unknown')}[/]",
                        classes="rec-status-msg",
                    )
                )

        self.post_message(RecommendationExecuted())
        await self._refresh()
