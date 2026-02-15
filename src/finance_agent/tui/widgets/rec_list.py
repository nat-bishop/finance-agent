"""Scrollable list of recommendation cards, grouped by group_id."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from .rec_card import RecCard


class RecList(VerticalScroll):
    """Displays pending recommendations grouped by group_id."""

    DEFAULT_CSS = """
    RecList {
        height: 1fr;
        padding: 0;
    }
    RecList .rec-list-title {
        text-style: bold;
        margin-bottom: 1;
    }
    RecList .rec-empty {
        color: $text-muted;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Pending Recs", classes="rec-list-title")
        yield Static("No pending recommendations", classes="rec-empty", id="rec-empty")

    def update_recs(self, recs: list[dict[str, Any]]) -> None:
        """Rebuild the rec card list from fresh data."""
        # Remove old cards
        for card in self.query(RecCard):
            card.remove()

        empty = self.query_one("#rec-empty", Static)

        if not recs:
            empty.display = True
            title = self.query_one(".rec-list-title", Static)
            title.update("Pending Recs")
            return

        empty.display = False

        # Group by group_id (None = ungrouped, each gets its own card)
        groups: dict[str | int, list[dict]] = {}
        ungrouped_idx = 0
        for rec in recs:
            gid = rec.get("group_id")
            if gid:
                groups.setdefault(gid, []).append(rec)
            else:
                groups[f"_single_{ungrouped_idx}"] = [rec]
                ungrouped_idx += 1

        title = self.query_one(".rec-list-title", Static)
        title.update(f"Pending Recs ({len(recs)})")

        for _gid, group_recs in groups.items():
            sorted_recs = sorted(group_recs, key=lambda r: r.get("leg_index", 0))
            self.mount(RecCard(sorted_recs))
