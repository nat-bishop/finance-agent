"""Knowledge base screen: KB content + git versions + analysis file browser."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from rich.markdown import Markdown
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    DirectoryTree,
    Static,
    TabbedContent,
    TabPane,
)

from ...kb_versioning import get_version_content, get_versions
from ..widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)


class AnalysisTree(DirectoryTree):
    """DirectoryTree that hides dotfiles."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if not p.name.startswith(".")]


class KnowledgeBaseScreen(Screen):
    """F2: Knowledge base viewer with git version history + analysis file browser."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f3", "app.switch_screen('recommendations')", "Recs"),
        ("f4", "app.switch_screen('portfolio')", "Portfolio"),
        ("f5", "app.switch_screen('history')", "History"),
        ("f6", "app.switch_screen('performance')", "P&L"),
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, analysis_dir: str = "workspace/analysis", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._analysis_dir = Path(analysis_dir)
        self._kb_path = self._analysis_dir / "knowledge_base.md"
        self._viewing_sha: str | None = None

    def compose(self) -> ComposeResult:
        with TabbedContent(id="kb-tabs"):
            with TabPane("Knowledge Base", id="kb-tab"):
                yield Static(
                    "[bold]Viewing old version — press Escape for current[/]",
                    id="kb-version-banner",
                )
                with VerticalScroll(id="kb-content-scroll"):
                    yield Static("Loading...", id="kb-content")
                yield Static("[bold]Version History[/]", id="kb-versions-title")
                yield DataTable(id="kb-versions-table")
            with TabPane("Files", id="files-tab"), Horizontal(id="file-browser-split"):
                yield AnalysisTree(self._analysis_dir, id="file-tree")
                with VerticalScroll(id="file-content-scroll"):
                    yield Static("Select a file to view", id="file-content")
        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        table = self.query_one("#kb-versions-table", DataTable)
        table.add_columns("Date", "Message")
        table.cursor_type = "row"
        await self._refresh()

    async def _refresh(self) -> None:
        """Reload current KB content, version history, and file tree."""
        self._viewing_sha = None
        self.query_one("#kb-version-banner").display = False

        # Load current content
        content_widget = self.query_one("#kb-content", Static)
        try:
            if self._kb_path.exists():
                text = self._kb_path.read_text(encoding="utf-8").strip()
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

        # Reload file tree
        try:
            tree = self.query_one("#file-tree", AnalysisTree)
            tree.reload()
        except Exception:
            logger.debug("Failed to reload file tree", exc_info=True)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Load a historical version when a row is selected."""
        sha = str(event.row_key.value)
        text = await get_version_content(sha)
        if text is None:
            return

        self._viewing_sha = sha
        self.query_one("#kb-version-banner").display = True
        self.query_one("#kb-content", Static).update(Markdown(text))

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Load and display the selected file."""
        path = event.path
        content_widget = self.query_one("#file-content", Static)

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            content_widget.update(f"[red]Cannot read {path.name}[/]")
            return

        suffix = path.suffix.lower()
        if suffix == ".md":
            try:
                content_widget.update(Markdown(text))
            except Exception:
                content_widget.update(text)
        elif suffix == ".py":
            try:
                content_widget.update(Syntax(text, "python", theme="monokai", line_numbers=True))
            except Exception:
                content_widget.update(text)
        elif suffix in (".json", ".jsonl"):
            try:
                content_widget.update(Syntax(text, "json", theme="monokai"))
            except Exception:
                content_widget.update(text)
        elif suffix == ".sql":
            try:
                content_widget.update(Syntax(text, "sql", theme="monokai"))
            except Exception:
                content_widget.update(text)
        else:
            content_widget.update(text)

    async def action_back(self) -> None:
        """Escape: return to current version, or back to dashboard."""
        if self._viewing_sha:
            await self._refresh()
        else:
            self.app.switch_screen("dashboard")

    async def action_refresh(self) -> None:
        await self._refresh()
