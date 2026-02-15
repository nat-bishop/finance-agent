"""Session history screen with drill-down."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ..services import TUIServices
from ..widgets.status_bar import StatusBar


class HistoryScreen(Screen):
    """F5: Session history with drill-down to trades/recs."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f2", "app.switch_screen('recommendations')", "Recs"),
        ("f3", "app.switch_screen('portfolio')", "Portfolio"),
        ("f4", "app.switch_screen('signals')", "Signals"),
        ("escape", "app.switch_screen('dashboard')", "Back"),
    ]

    def __init__(self, services: TUIServices, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services = services

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="history-container"):
            yield Static("[bold]Session History[/]")
            yield DataTable(id="sessions-table")

            yield Static("")
            yield Static("[bold]Session Details[/]", id="detail-title")
            yield DataTable(id="detail-trades-table")
            yield DataTable(id="detail-recs-table")

        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        sess_table = self.query_one("#sessions-table", DataTable)
        sess_table.add_columns("ID", "Started", "Ended", "Trades", "Recs", "PnL", "Summary")
        sess_table.cursor_type = "row"

        # Detail tables
        trades_table = self.query_one("#detail-trades-table", DataTable)
        trades_table.add_columns("Exchange", "Ticker", "Action", "Side", "Qty", "Price", "Status")

        recs_table = self.query_one("#detail-recs-table", DataTable)
        recs_table.add_columns("Exchange", "Market", "Action", "Side", "Qty", "Price", "Status")

        await self._refresh()

    async def _refresh(self) -> None:
        sessions = self._services.get_sessions(limit=20)
        table = self.query_one("#sessions-table", DataTable)
        table.clear()

        for sess in sessions:
            started = str(sess.get("started_at", ""))[:16]
            ended = str(sess.get("ended_at", ""))[:16] if sess.get("ended_at") else "running"
            pnl = f"${sess['pnl_usd']:.2f}" if sess.get("pnl_usd") is not None else ""
            summary = str(sess.get("summary", ""))[:30]
            table.add_row(
                str(sess.get("id", "")),
                started,
                ended,
                str(sess.get("trades_placed", 0)),
                str(sess.get("recommendations_made", 0)),
                pnl,
                summary,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Drill down into a session."""
        table = self.query_one("#sessions-table", DataTable)
        row_data = table.get_row(event.row_key)
        session_id = str(row_data[0])

        self.query_one("#detail-title", Static).update(f"[bold]Session {session_id} Details[/]")

        # Load trades for session
        trades = self._services.get_trades(session_id=session_id, limit=20)
        trades_table = self.query_one("#detail-trades-table", DataTable)
        trades_table.clear()
        for t in trades:
            trades_table.add_row(
                str(t.get("exchange", ""))[:2].upper(),
                str(t.get("ticker", "")),
                str(t.get("action", "")),
                str(t.get("side", "")),
                str(t.get("count", "")),
                str(t.get("price_cents", "")),
                str(t.get("status", "")),
            )

        # Load recs for session
        recs = self._services.get_recommendations(session_id=session_id, limit=20)
        recs_table = self.query_one("#detail-recs-table", DataTable)
        recs_table.clear()
        for r in recs:
            recs_table.add_row(
                str(r.get("exchange", ""))[:2].upper(),
                str(r.get("market_title", r.get("market_id", "")))[:30],
                str(r.get("action", "")),
                str(r.get("side", "")),
                str(r.get("quantity", "")),
                str(r.get("price_cents", "")),
                str(r.get("status", "")),
            )
