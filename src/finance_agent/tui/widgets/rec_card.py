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

        if len(legs) > 1:
            yield Static(
                f"Group #{group_id} ({len(legs)} legs)",
                classes="rec-title",
            )
        elif legs:
            yield Static(
                f"{legs[0]['exchange'].upper()}: {(legs[0].get('market_title') or '')[:50]}",
                classes="rec-title",
            )
        else:
            yield Static("Empty recommendation", classes="rec-title")

        for leg in legs:
            exch = "K" if leg["exchange"] == "kalshi" else "PM"
            yield Static(
                f"  {exch}: {leg['action'].upper()} {leg['side'].upper()} "
                f"@ {leg['price_cents']}c x{leg['quantity']}",
            )

        # Group-level details
        details = []
        if self.group.get("estimated_edge_pct"):
            details.append(f"Edge: {self.group['estimated_edge_pct']:.1f}%")
        if self.group.get("thesis"):
            thesis = self.group["thesis"][:80]
            if len(self.group["thesis"]) > 80:
                thesis += "..."
            details.append(thesis)
        if details:
            yield Static(" | ".join(details[:1]), classes="rec-detail")
            if len(details) > 1:
                yield Static(details[1], classes="rec-detail")

        # Expiry
        expires_at = self.group.get("expires_at")
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
        with Horizontal(classes="rec-actions"):
            yield Button(
                "Execute" if len(legs) <= 1 else "Execute All",
                id=f"exec-group-{group_id}",
                variant="success",
            )
            yield Button(
                "Reject",
                id=f"reject-group-{group_id}",
                variant="error",
            )
