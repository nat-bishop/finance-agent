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

        # Clear existing cards
        for card in container.query(RecCard):
            card.remove()
        for static in container.query(".rec-status-msg"):
            static.remove()

        # Get all recommendations (pending first, then recent executed/rejected)
        pending = self._services.get_pending_recs()
        recent = self._services.get_recommendations(limit=20)

        # Group pending by group_id
        groups: dict[str | int, list[dict]] = {}
        ungrouped_idx = 0
        for rec in pending:
            gid = rec.get("group_id")
            if gid:
                groups.setdefault(gid, []).append(rec)
            else:
                groups[f"_single_{ungrouped_idx}"] = [rec]
                ungrouped_idx += 1

        if not groups:
            container.mount(Static("[dim]No pending recommendations[/]", classes="rec-status-msg"))

        for _gid, group_recs in groups.items():
            sorted_recs = sorted(group_recs, key=lambda r: r.get("leg_index", 0))
            container.mount(RecCard(sorted_recs))

        # Show recent non-pending
        non_pending = [r for r in recent if r.get("status") != "pending"]
        if non_pending:
            container.mount(Static("\n[bold]Recent[/]", classes="rec-status-msg"))
            for rec in non_pending[:10]:
                status = rec.get("status", "?")
                exch = rec.get("exchange", "?").upper()
                title = rec.get("market_title", rec.get("market_id", ""))[:40]
                container.mount(
                    Static(
                        f"  [{status}] {exch}: {rec.get('action', '?').upper()} "
                        f"{rec.get('side', '?').upper()} {title}",
                        classes="rec-status-msg",
                    )
                )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id.startswith("exec-group-"):
            group_id = btn_id[len("exec-group-") :]
            recs = [r for r in self._services.get_pending_recs() if r.get("group_id") == group_id]
            if recs:
                await self._confirm_and_execute(recs, group_id=group_id)

        elif btn_id.startswith("exec-"):
            rec_id = int(btn_id[len("exec-") :])
            recs = [r for r in self._services.get_pending_recs() if r["id"] == rec_id]
            if recs:
                await self._confirm_and_execute(recs, rec_ids=[rec_id])

        elif btn_id.startswith("reject-"):
            rec_id = int(btn_id[len("reject-") :])
            await self._services.reject_recommendation(rec_id)
            await self._refresh()

    async def _confirm_and_execute(
        self,
        recs: list[dict],
        group_id: str | None = None,
        rec_ids: list[int] | None = None,
    ) -> None:
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self.run_worker(self._do_execute(group_id, rec_ids))

        self.app.push_screen(ConfirmModal(recs), callback=on_confirm)

    async def _do_execute(self, group_id: str | None, rec_ids: list[int] | None) -> None:
        results = await self._services.execute_recommendation_group(
            group_id=group_id, rec_ids=rec_ids
        )

        # Show results
        container = self.query_one("#recs-container", VerticalScroll)
        for r in results:
            if r["status"] == "executed":
                container.mount(
                    Static(
                        f"  [green]Executed rec #{r['rec_id']}: "
                        f"order {r.get('order_id', 'N/A')}[/]",
                        classes="rec-status-msg",
                    )
                )
            else:
                container.mount(
                    Static(
                        f"  [red]Failed rec #{r['rec_id']}: {r.get('error', 'unknown')}[/]",
                        classes="rec-status-msg",
                    )
                )

        self.post_message(RecommendationExecuted())
        await self._refresh()
