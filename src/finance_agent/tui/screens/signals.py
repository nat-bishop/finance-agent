"""Signals screen."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ..services import TUIServices
from ..widgets.status_bar import StatusBar


class SignalsScreen(Screen):
    """F4: Signal table."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f2", "app.switch_screen('recommendations')", "Recs"),
        ("f3", "app.switch_screen('portfolio')", "Portfolio"),
        ("f5", "app.switch_screen('history')", "History"),
        ("escape", "app.switch_screen('dashboard')", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, services: TUIServices, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services = services

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="signals-container"):
            yield Static("[bold]Pending Signals[/]")
            yield DataTable(id="signals-table")

        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        # Signals table
        sig_table = self.query_one("#signals-table", DataTable)
        sig_table.add_columns("Type", "Exchange", "Ticker", "Strength", "Edge %", "Status")

        await self._refresh()

    async def _refresh(self) -> None:
        # Pending signals
        signals = self._services.get_signals(status="pending", limit=50)
        sig_table = self.query_one("#signals-table", DataTable)
        sig_table.clear()
        for sig in signals:
            sig_table.add_row(
                str(sig.get("scan_type", "")),
                str(sig.get("exchange", "")),
                str(sig.get("ticker", "")),
                f"{sig.get('signal_strength', 0):.2f}" if sig.get("signal_strength") else "",
                f"{sig.get('estimated_edge_pct', 0):.1f}" if sig.get("estimated_edge_pct") else "",
                str(sig.get("status", "")),
            )

    async def action_refresh(self) -> None:
        await self._refresh()
