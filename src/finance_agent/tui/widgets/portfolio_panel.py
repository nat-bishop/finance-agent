"""Compact portfolio summary for the sidebar."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class PortfolioPanel(Vertical):
    """Shows balances and position counts for both exchanges."""

    DEFAULT_CSS = """
    PortfolioPanel {
        height: auto;
        padding: 1;
        border: solid $primary;
        margin: 0 0 1 0;
    }
    PortfolioPanel .portfolio-title {
        text-style: bold;
        margin-bottom: 1;
    }
    PortfolioPanel .balance-line {
        margin: 0;
    }
    """

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

        pm = data.get("polymarket", {})
        if pm:
            pm_balance = pm.get("balance", {})
            pm_bal_val = pm_balance.get("balance", pm_balance.get("cash_balance", "?"))
            if isinstance(pm_bal_val, int | float):
                pm_bal_val = f"${pm_bal_val:.2f}"
            pm_positions = pm.get("positions", {})
            pm_pos_list = pm_positions.get("positions", [])
            pm_pos_count = len(pm_pos_list) if isinstance(pm_pos_list, list) else 0
            lines.append(f"PM: {pm_bal_val} | {pm_pos_count} positions")

        content.update("\n".join(lines) if lines else "No data")
