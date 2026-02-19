"""Performance screen: hypothetical P&L tracking for recommendations."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ..services import TUIServices
from ..widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)


class PerformanceScreen(Screen):
    """F6: Hypothetical P&L tracking and recommendation performance."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f2", "app.switch_screen('knowledge_base')", "KB"),
        ("f3", "app.switch_screen('recommendations')", "Recs"),
        ("f4", "app.switch_screen('portfolio')", "Portfolio"),
        ("f5", "app.switch_screen('history')", "History"),
        ("escape", "app.switch_screen('dashboard')", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, services: TUIServices, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services = services

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="performance-container"):
            yield Static("[bold]Hypothetical Performance[/]", id="perf-title")
            yield Static("Loading...", id="perf-summary")
            yield Static("")
            yield Static("[bold]Settled Recommendations[/]")
            yield DataTable(id="settled-table")
            yield Static("")
            yield Static("[bold]Awaiting Settlement[/]")
            yield DataTable(id="pending-table")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        settled = self.query_one("#settled-table", DataTable)
        settled.add_columns("ID", "Strategy", "Thesis", "Est Edge", "P&L", "Exposure", "Legs")

        pending = self.query_one("#pending-table", DataTable)
        pending.add_columns("ID", "Strategy", "Thesis", "Legs", "Settled/Total", "Depth Warns")

        await self._refresh()
        self.set_interval(30, self._refresh)

    async def _refresh(self) -> None:
        try:
            perf = self._services.get_performance_summary()
            self._update_summary(perf)
            self._update_settled_table(perf.get("settled_groups", []))
            self._update_pending_table(perf.get("pending_groups", []))
        except Exception:
            logger.debug("Failed to refresh performance", exc_info=True)

    def _update_summary(self, perf: dict[str, Any]) -> None:
        total = perf.get("total_pnl_usd", 0)
        color = "green" if total >= 0 else "red"
        settled = perf.get("total_settled", 0)
        wins = perf.get("wins", 0)
        losses = perf.get("losses", 0)
        win_rate = perf.get("win_rate", 0)
        edge_err = perf.get("avg_edge_error")

        parts = [
            f"[{color}]Total Hypothetical P&L: ${total:+.2f}[/]",
            (
                f"Record: {wins}W / {losses}L ({win_rate:.0f}% win rate)"
                if settled
                else "No settled recommendations yet"
            ),
        ]
        if edge_err is not None:
            parts.append(f"Avg Edge Error: {edge_err:.1f}pp")
        self.query_one("#perf-summary", Static).update("\n".join(parts))

    def _update_settled_table(self, groups: list[dict[str, Any]]) -> None:
        table = self.query_one("#settled-table", DataTable)
        table.clear()
        for g in groups:
            pnl = g.get("hypothetical_pnl_usd", 0)
            pnl_str = f"[green]${pnl:+.2f}[/]" if pnl >= 0 else f"[red]${pnl:+.2f}[/]"
            edge = g.get("estimated_edge_pct")
            edge_str = f"{edge:.1f}%" if edge is not None else "-"
            exposure = g.get("total_exposure_usd")
            exposure_str = f"${exposure:.2f}" if exposure else "-"
            thesis = str(g.get("thesis", ""))[:50]
            legs = len(g.get("legs", []))
            table.add_row(
                str(g.get("id", "")),
                str(g.get("strategy", "")),
                thesis,
                edge_str,
                pnl_str,
                exposure_str,
                str(legs),
            )

    def _update_pending_table(self, groups: list[dict[str, Any]]) -> None:
        from ...fees import assess_depth_concern

        table = self.query_one("#pending-table", DataTable)
        table.clear()
        for g in groups:
            legs = g.get("legs", [])
            settled_count = sum(1 for lg in legs if lg.get("settlement_value") is not None)
            total_legs = len(legs)
            depth_warnings = sum(1 for lg in legs if assess_depth_concern(lg) is not None)
            thesis = str(g.get("thesis", ""))[:50]
            table.add_row(
                str(g.get("id", "")),
                str(g.get("strategy", "")),
                thesis,
                str(total_legs),
                f"{settled_count}/{total_legs}",
                str(depth_warnings) if depth_warnings else "",
            )

    async def action_refresh(self) -> None:
        await self._refresh()
