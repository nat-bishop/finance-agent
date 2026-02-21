"""Session history screen: journal-style session log viewer."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ..services import TUIServices
from ..widgets.status_bar import StatusBar


class HistoryScreen(Screen):
    """F5: Session journal — investigation summaries with drill-down."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f2", "app.switch_screen('knowledge_base')", "KB"),
        ("f3", "app.switch_screen('recommendations')", "Recs"),
        ("f4", "app.switch_screen('portfolio')", "Portfolio"),
        ("f6", "app.switch_screen('performance')", "P&L"),
        ("escape", "app.switch_screen('dashboard')", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, services: TUIServices, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services = services
        self._sessions: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="history-split"):
            with VerticalScroll(id="session-list-pane"):
                yield Static("[bold]Sessions[/]")
                yield DataTable(id="sessions-table")
            with VerticalScroll(id="session-detail-pane"):
                yield Static("", id="detail-header")
                yield Static(
                    "[dim]Select a session to view its summary[/]",
                    id="session-log-content",
                )
                yield Static("[bold]Recommendations[/]", id="recs-section-title")
                yield DataTable(id="detail-recs-table")
                yield Static("[bold]Trades[/]", id="trades-section-title")
                yield DataTable(id="detail-trades-table")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        sess_table = self.query_one("#sessions-table", DataTable)
        sess_table.add_columns("Date", "ID", "Recs", "Trades")
        sess_table.cursor_type = "row"

        recs_table = self.query_one("#detail-recs-table", DataTable)
        recs_table.add_columns("Group", "Market", "Action", "Side", "Qty", "Price", "Status")

        trades_table = self.query_one("#detail-trades-table", DataTable)
        trades_table.add_columns("Ticker", "Action", "Side", "Qty", "Price", "Status")

        await self._refresh()

    async def _refresh(self) -> None:
        self._sessions = self._services.get_sessions(limit=30)
        table = self.query_one("#sessions-table", DataTable)
        table.clear()

        for sess in self._sessions:
            started = str(sess.get("started_at", ""))[:10]
            sid = str(sess.get("id", ""))
            has_log = sess.get("has_log", False)
            id_display = f"\u2022 {sid}" if has_log else f"  {sid}"
            table.add_row(
                started,
                id_display,
                str(sess.get("recommendations_made", 0)),
                str(sess.get("trades_placed", 0)),
                key=sid,
            )

        # Auto-select first session
        if self._sessions:
            first_id = str(self._sessions[0].get("id", ""))
            self._load_session_detail(first_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Load session detail when a row is clicked/selected."""
        session_id = str(event.row_key.value)
        self._load_session_detail(session_id)

    def _load_session_detail(self, session_id: str) -> None:
        """Populate the right pane with log, recs, and trades for a session."""
        sess_meta = next(
            (s for s in self._sessions if str(s.get("id", "")) == session_id),
            None,
        )
        started = str(sess_meta.get("started_at", ""))[:16] if sess_meta else ""
        self.query_one("#detail-header", Static).update(
            f"[bold]Session {session_id}[/]  {started}"
        )

        # Load session log (prose summary)
        log_widget = self.query_one("#session-log-content", Static)
        logs = self._services.get_session_logs(session_id=session_id)
        if logs:
            content = logs[0].get("content", "")
            if content.strip():
                try:
                    log_widget.update(Markdown(content))
                except Exception:
                    log_widget.update(content)
            else:
                log_widget.update("[dim italic]Empty session log[/]")
        else:
            log_widget.update("[dim italic]No summary available for this session[/]")

        # Load recommendations
        groups = self._services.get_recommendations(session_id=session_id, limit=20)
        recs_table = self.query_one("#detail-recs-table", DataTable)
        recs_table.clear()
        for group in groups:
            gid = str(group.get("id", ""))
            g_status = str(group.get("status", ""))
            for leg in group.get("legs", []):
                recs_table.add_row(
                    gid,
                    str(leg.get("market_title", leg.get("market_id", "")))[:40],
                    str(leg.get("action", "")),
                    str(leg.get("side", "")),
                    str(leg.get("quantity", "")),
                    str(leg.get("price_cents", "")),
                    g_status,
                )

        # Load trades
        trades = self._services.get_trades(session_id=session_id, limit=20)
        trades_table = self.query_one("#detail-trades-table", DataTable)
        trades_table.clear()
        for t in trades:
            trades_table.add_row(
                str(t.get("ticker", "")),
                str(t.get("action", "")),
                str(t.get("side", "")),
                str(t.get("quantity", "")),
                str(t.get("price_cents", "")),
                str(t.get("status", "")),
            )

    async def action_refresh(self) -> None:
        await self._refresh()
