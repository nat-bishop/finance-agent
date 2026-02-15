"""Single recommendation card widget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static


class RecCard(Vertical):
    """Displays a recommendation group with its legs."""

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

    def __init__(self, group: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.group = group

    def compose(self) -> ComposeResult:
        legs = self.group.get("legs", [])
        group_id = self.group["id"]

        yield Static(
            f"Group #{group_id} ({len(legs)} legs)",
            classes="rec-title",
        )

        for leg in legs:
            exch = "K" if leg["exchange"] == "kalshi" else "PM"
            yield Static(
                f"  {exch}: {leg['action'].upper()} {leg['side'].upper()} "
                f"@ {leg['price_cents']}c x{leg['quantity']}",
            )

        # Group-level details
        if self.group.get("estimated_edge_pct"):
            yield Static(f"Edge: {self.group['estimated_edge_pct']:.1f}%", classes="rec-detail")
        if thesis := self.group.get("thesis"):
            yield Static(
                f"{thesis[:80]}..." if len(thesis) > 80 else thesis,
                classes="rec-detail",
            )

        # Expiry
        if expires_at := self.group.get("expires_at"):
            try:
                mins = int(
                    (datetime.fromisoformat(expires_at) - datetime.now(UTC)).total_seconds() / 60
                )
                label = f"Expires in {mins}m" if mins > 0 else "[bold red]EXPIRED[/]"
                yield Static(label, classes="rec-detail")
            except (ValueError, TypeError):
                pass

        # Action buttons
        with Horizontal(classes="rec-actions"):
            yield Button(
                "Execute All",
                id=f"exec-group-{group_id}",
                variant="success",
            )
            yield Button(
                "Reject",
                id=f"reject-group-{group_id}",
                variant="error",
            )
