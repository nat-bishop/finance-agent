"""Signals and calibration screen."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ..services import TUIServices
from ..widgets.status_bar import StatusBar


class SignalsScreen(Screen):
    """F4: Signal table + calibration summary."""

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

            yield Static("")
            yield Static("[bold]Calibration[/]")
            yield Static("Loading...", id="calibration-summary")

            yield Static("")
            yield Static("[bold]Signal History[/]")
            yield DataTable(id="signal-history-table")

        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        # Signals table
        sig_table = self.query_one("#signals-table", DataTable)
        sig_table.add_columns("Type", "Exchange", "Ticker", "Strength", "Edge %", "Status")

        # History table
        hist_table = self.query_one("#signal-history-table", DataTable)
        hist_table.add_columns("Scan Type", "Count", "Avg Edge %")

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

        # Calibration
        state = self._services.get_session_state()
        cal = state.get("calibration")
        if cal:
            cal_text = (
                f"Total predictions: {cal['total']} | "
                f"Correct: {cal['correct']} | "
                f"Brier score: {cal['brier_score']:.4f}\n"
            )
            for bucket in cal.get("buckets", []):
                cal_text += (
                    f"  {bucket['range']}: {bucket['count']} predictions, "
                    f"{bucket['accuracy']:.0%} accuracy\n"
                )
            self.query_one("#calibration-summary", Static).update(cal_text)
        else:
            self.query_one("#calibration-summary", Static).update("No predictions resolved yet")

        # Signal history
        hist = state.get("signal_history", [])
        hist_table = self.query_one("#signal-history-table", DataTable)
        hist_table.clear()
        for h in hist:
            hist_table.add_row(
                str(h.get("scan_type", "")),
                str(h.get("count", "")),
                f"{h.get('avg_edge', 0):.1f}" if h.get("avg_edge") else "",
            )

    async def action_refresh(self) -> None:
        await self._refresh()
