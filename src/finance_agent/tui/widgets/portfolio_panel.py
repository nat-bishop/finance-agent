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
        lines = []

        kalshi = data.get("kalshi", {})
        k_balance = kalshi.get("balance", {})
        k_bal_val = k_balance.get("balance", k_balance.get("available_balance", "?"))
        if isinstance(k_bal_val, int | float):
            k_bal_val = f"${k_bal_val / 100:.2f}"
        k_positions = kalshi.get("positions", {})
        k_pos_list = k_positions.get("market_positions", [])
        k_pos_count = len(k_pos_list) if isinstance(k_pos_list, list) else 0
        lines.append(f"Kalshi: {k_bal_val} | {k_pos_count} positions")

        content.update("\n".join(lines) if lines else "No data")
