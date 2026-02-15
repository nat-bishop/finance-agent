"""Confirmation dialog before order execution."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """Shows order details and asks for confirmation."""

    def __init__(self, group: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.group = group

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static("[bold]Confirm Execution[/]")
            yield Static("")

            total_cost = 0.0
            for leg in self.group.get("legs", []):
                exch = leg["exchange"].upper()
                cost = leg["price_cents"] * leg["quantity"] / 100
                total_cost += cost
                yield Static(
                    f"  {exch}: {leg['action'].upper()} {leg['side'].upper()} "
                    f"{(leg.get('market_title') or leg['market_id'])[:40]}"
                )
                yield Static(f"    @ {leg['price_cents']}c x{leg['quantity']} = ${cost:.2f}")

            yield Static("")
            yield Static(f"[bold]Total cost: ${total_cost:.2f}[/]")

            if self.group.get("equivalence_notes"):
                yield Static(f"[dim]Equivalence: {self.group['equivalence_notes'][:60]}[/]")

            with Horizontal(id="confirm-actions"):
                yield Button("Confirm", id="confirm-yes", variant="success")
                yield Button("Cancel", id="confirm-no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)
