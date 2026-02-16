"""Compact portfolio summary for the sidebar."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class PortfolioPanel(Vertical):
    """Shows balances and position counts for both exchanges."""

    def compose(self) -> ComposeResult:
        yield Static("Portfolio", classes="portfolio-title")
        yield Static("Loading...", id="portfolio-content")

    def update_data(self, data: dict[str, Any]) -> None:
        """Update with portfolio data from services.get_portfolio()."""
        content = self.query_one("#portfolio-content", Static)

        kalshi = data.get("kalshi", {})
        balance = kalshi.get("balance", {})
        bal_val = balance.get("balance", balance.get("available_balance", "?"))
        if isinstance(bal_val, int | float):
            bal_val = f"${bal_val / 100:.2f}"
        positions = kalshi.get("positions", {}).get("market_positions", [])
        pos_count = len(positions) if isinstance(positions, list) else 0

        content.update(f"Kalshi: {bal_val} | {pos_count} positions")
