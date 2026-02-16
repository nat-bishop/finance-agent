"""Knowledge base summary panel for the sidebar."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

logger = logging.getLogger(__name__)

_KB_PATH = Path("/workspace/analysis/knowledge_base.md")
_MAX_DISPLAY_CHARS = 2000


class KBPanel(VerticalScroll):
    """Displays knowledge_base.md content in the sidebar."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]Knowledge Base[/]", id="kb-title")
        yield Static("No knowledge base yet", id="kb-content")

    def on_mount(self) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        """Re-read knowledge_base.md and update display."""
        content = self.query_one("#kb-content", Static)
        try:
            if _KB_PATH.exists():
                text = _KB_PATH.read_text(encoding="utf-8").strip()
                if text:
                    if len(text) > _MAX_DISPLAY_CHARS:
                        text = text[:_MAX_DISPLAY_CHARS] + "\n\n... (truncated)"
                    content.update(Markdown(text))
                else:
                    content.update("Empty knowledge base")
            else:
                content.update("No knowledge base yet")
        except Exception:
            logger.debug("Failed to read knowledge base", exc_info=True)
            content.update("Error reading knowledge base")
