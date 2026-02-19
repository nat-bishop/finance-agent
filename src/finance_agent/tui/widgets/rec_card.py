"""Single recommendation card widget."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from ...constants import STATUS_PENDING


class RecCard(Vertical):
    """Displays a recommendation group with its legs."""

    def __init__(self, group: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.group = group

    def _compose_legs(self) -> Iterable[Static]:
        for leg in self.group.get("legs", []):
            action = (leg.get("action") or "?").upper()
            side = (leg.get("side") or "?").upper()
            price = leg.get("price_cents")
            qty = leg.get("quantity")
            maker = " [maker]" if leg.get("is_maker") else ""

            price_str = f"@ {price}c" if price is not None else "@ ?"
            qty_str = f"x{qty}" if qty is not None else ""

            yield Static(f"  K: {action} {side} {price_str} {qty_str}{maker}")

    def _compose_metrics(self) -> Iterable[Static]:
        edge = self.group.get("computed_edge_pct") or self.group.get("estimated_edge_pct")
        if edge is not None:
            label = "computed" if self.group.get("computed_edge_pct") else "estimated"
            yield Static(f"Edge: {edge:.1f}% ({label})", classes="rec-detail")

        if fees := self.group.get("computed_fees_usd"):
            yield Static(f"Fees: ${fees:.4f}", classes="rec-detail")

        if exposure := self.group.get("total_exposure_usd"):
            yield Static(f"Exposure: ${exposure:.2f}", classes="rec-detail")

        if thesis := self.group.get("thesis"):
            yield Static(
                f"{thesis[:80]}..." if len(thesis) > 80 else thesis,
                classes="rec-detail",
            )

    def _compose_close_time(self) -> Iterable[Static]:
        """Show earliest market close time across all legs."""
        earliest: datetime | None = None
        for leg in self.group.get("legs", []):
            snap_json = leg.get("orderbook_snapshot_json")
            if not snap_json:
                continue
            try:
                snap = json.loads(snap_json) if isinstance(snap_json, str) else snap_json
                ct = snap.get("close_time")
                if not ct:
                    continue
                close_dt = datetime.fromisoformat(str(ct))
                if earliest is None or close_dt < earliest:
                    earliest = close_dt
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

        if earliest is None:
            return

        now = datetime.now(UTC)
        delta = earliest - now
        hours = delta.total_seconds() / 3600
        if hours <= 0:
            yield Static("[bold red]Market closed[/]", classes="rec-stale")
        elif hours < 24:
            yield Static(f"[red]Market closes in {int(hours)}h[/]", classes="rec-stale")
        elif hours < 24 * 7:
            days = int(hours / 24)
            yield Static(f"[yellow]Market closes in {days}d[/]", classes="rec-detail")
        else:
            days = int(hours / 24)
            yield Static(f"Market closes in {days}d", classes="rec-detail")

    def _compose_staleness(self) -> Iterable[Static]:
        if expires_at := self.group.get("expires_at"):
            try:
                mins = int(
                    (datetime.fromisoformat(expires_at) - datetime.now(UTC)).total_seconds() / 60
                )
                if mins <= 0:
                    yield Static("[bold red]EXPIRED[/]", classes="rec-stale")
                elif mins <= 10:
                    yield Static(
                        f"[yellow]Expires in {mins}m — prices may have moved[/]",
                        classes="rec-stale",
                    )
                else:
                    yield Static(f"Expires in {mins}m", classes="rec-detail")
            except (ValueError, TypeError):
                pass

        if created_at := self.group.get("created_at"):
            try:
                age_min = int(
                    (datetime.now(UTC) - datetime.fromisoformat(created_at)).total_seconds() / 60
                )
                if age_min > 10 and not self.group.get("expires_at"):
                    yield Static(f"[yellow]Stale: created {age_min}m ago[/]", classes="rec-stale")
            except (ValueError, TypeError):
                pass

    def compose(self) -> ComposeResult:
        legs = self.group.get("legs", [])
        group_id = self.group["id"]
        status = self.group.get("status", STATUS_PENDING)

        yield Static(
            f"Group #{group_id} ({len(legs)} legs) [{status}]",
            classes="rec-title",
        )
        yield from self._compose_legs()
        yield from self._compose_metrics()
        yield from self._compose_close_time()
        yield from self._compose_staleness()

        if status == STATUS_PENDING:
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
