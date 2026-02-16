"""Scrollable list of recommendation cards."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from .rec_card import RecCard


class RecList(VerticalScroll):
    """Displays pending recommendation groups."""

    def compose(self) -> ComposeResult:
        yield Static("Pending Recs", classes="rec-list-title")
        yield Static("No pending recommendations", classes="rec-empty", id="rec-empty")

    def update_recs(self, groups: list[dict[str, Any]]) -> None:
        """Rebuild the rec card list from fresh group data."""
        for card in self.query(RecCard):
            card.remove()

        empty = self.query_one("#rec-empty", Static)
        title = self.query_one(".rec-list-title", Static)
        empty.display = not groups

        if not groups:
            title.update("Pending Recs")
            return

        leg_count = sum(len(g.get("legs", [])) for g in groups)
        title.update(f"Pending Recs ({leg_count} legs in {len(groups)} groups)")
        for group in groups:
            self.mount(RecCard(group))
