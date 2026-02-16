"""Bottom status bar showing session info."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    """Persistent bottom bar: session, cost, rec count."""

    session_id: reactive[str] = reactive("")
    total_cost: reactive[float] = reactive(0.0)
    rec_count: reactive[int] = reactive(0)

    def render(self) -> str:
        now = datetime.now(UTC).strftime("%H:%M")
        return (
            f" Session: {self.session_id}"
            f" | Cost: ${self.total_cost:.4f}"
            f" | Recs: {self.rec_count}"
            f" | {now}"
        )
