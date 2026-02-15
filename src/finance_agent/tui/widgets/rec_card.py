"""Single recommendation card widget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


class RecCard(Vertical):
    """Displays a single recommendation or a group of paired legs."""

    DEFAULT_CSS = """
    RecCard {
        height: auto;
        padding: 1;
        border: solid $warning;
        margin: 0 0 1 0;
    }
    RecCard .rec-title {
        text-style: bold;
    }
    RecCard .rec-detail {
        color: $text-muted;
    }
    RecCard .rec-actions {
        height: 3;
        margin-top: 1;
    }
    RecCard .rec-actions Button {
        margin-right: 1;
    }
    """

    def __init__(self, recs: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.recs = recs
        self._group_id = recs[0].get("group_id") if recs else None

    def compose(self) -> ComposeResult:
        if not self.recs:
            yield Static("Empty recommendation")
            return

        first = self.recs[0]
        if self._group_id and len(self.recs) > 1:
            yield Static(
                f"Group {self._group_id} ({len(self.recs)} legs)",
                classes="rec-title",
            )
        else:
            yield Static(
                f"{first['exchange'].upper()}: {first['market_title'][:50]}",
                classes="rec-title",
            )

        for rec in self.recs:
            exch = "K" if rec["exchange"] == "kalshi" else "PM"
            yield Static(
                f"  {exch}: {rec['action'].upper()} {rec['side'].upper()} "
                f"@ {rec['price_cents']}c x{rec['quantity']}",
            )

        # Details from first leg
        details = []
        if first.get("estimated_edge_pct"):
            details.append(f"Edge: {first['estimated_edge_pct']:.1f}%")
        if first.get("confidence"):
            details.append(f"Conf: {first['confidence']}")
        if first.get("thesis"):
            thesis = first["thesis"][:80]
            if len(first["thesis"]) > 80:
                thesis += "..."
            details.append(thesis)
        if details:
            yield Static(" | ".join(details[:2]), classes="rec-detail")
            if len(details) > 2:
                yield Static(details[2], classes="rec-detail")

        # Expiry
        expires_at = first.get("expires_at")
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at)
                now = datetime.now(UTC)
                remaining = exp - now
                mins = int(remaining.total_seconds() / 60)
                if mins > 0:
                    yield Static(f"Expires in {mins}m", classes="rec-detail")
                else:
                    yield Static("[bold red]EXPIRED[/]", classes="rec-detail")
            except (ValueError, TypeError):
                pass

        # Action buttons
        rec_id = first["id"]
        with Horizontal(classes="rec-actions"):
            if self._group_id and len(self.recs) > 1:
                yield Button(
                    "Execute All",
                    id=f"exec-group-{self._group_id}",
                    variant="success",
                )
            else:
                yield Button(
                    "Execute",
                    id=f"exec-{rec_id}",
                    variant="success",
                )
            yield Button(
                "Reject",
                id=f"reject-{rec_id}",
                variant="error",
            )
