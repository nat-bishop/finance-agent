"""Knowledge base screen: full content display + git version history."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ...kb_versioning import get_version_content, get_versions
from ..widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)

_KB_PATH = Path("/workspace/analysis/knowledge_base.md")


class KnowledgeBaseScreen(Screen):
    """F2: Knowledge base viewer with git version history."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f3", "app.switch_screen('recommendations')", "Recs"),
        ("f4", "app.switch_screen('portfolio')", "Portfolio"),
        ("f5", "app.switch_screen('history')", "History"),
        ("f6", "app.switch_screen('performance')", "P&L"),
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._viewing_sha: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Viewing old version — press Escape for current[/]",
            id="kb-version-banner",
        )
        with VerticalScroll(id="kb-content-scroll"):
            yield Static("Loading...", id="kb-content")
        yield Static("[bold]Version History[/]", id="kb-versions-title")
        yield DataTable(id="kb-versions-table")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        table = self.query_one("#kb-versions-table", DataTable)
        table.add_columns("Date", "Message")
        table.cursor_type = "row"
        await self._refresh()

    async def _refresh(self) -> None:
        """Reload current KB content and version history."""
        self._viewing_sha = None
        self.query_one("#kb-version-banner").display = False

        # Load current content
        content_widget = self.query_one("#kb-content", Static)
        try:
            if _KB_PATH.exists():
                text = _KB_PATH.read_text(encoding="utf-8").strip()
                if text:
                    content_widget.update(Markdown(text))
                else:
                    content_widget.update("Empty knowledge base")
            else:
                content_widget.update("No knowledge base yet")
        except Exception:
            logger.debug("Failed to read knowledge base", exc_info=True)
            content_widget.update("Error reading knowledge base")

        # Load version history
        versions = await get_versions()
        table = self.query_one("#kb-versions-table", DataTable)
        table.clear()

        for v in versions:
            date_short = v.date[:19]  # trim timezone
            table.add_row(date_short, v.message, key=v.sha)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Load a historical version when a row is selected."""
        sha = str(event.row_key.value)
        text = await get_version_content(sha)
        if text is None:
            return

        self._viewing_sha = sha
        self.query_one("#kb-version-banner").display = True
        self.query_one("#kb-content", Static).update(Markdown(text))

    async def action_back(self) -> None:
        """Escape: return to current version, or back to dashboard."""
        if self._viewing_sha:
            await self._refresh()
        else:
            self.app.switch_screen("dashboard")

    async def action_refresh(self) -> None:
        await self._refresh()
