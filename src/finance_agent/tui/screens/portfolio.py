"""Portfolio screen: balances, positions, orders with management."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Static

from ..services import TUIServices
from ..widgets.status_bar import StatusBar

logger = logging.getLogger(__name__)


class PortfolioScreen(Screen):
    """F3: Balances, positions, resting orders with amend/cancel."""

    BINDINGS: ClassVar[list] = [
        ("f1", "app.switch_screen('dashboard')", "Chat"),
        ("f2", "app.switch_screen('recommendations')", "Recs"),
        ("f4", "app.switch_screen('history')", "History"),
        ("escape", "app.switch_screen('dashboard')", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, services: TUIServices, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._services = services

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="portfolio-container"):
            # Balances
            with Horizontal():
                yield Static("Loading...", id="kalshi-balance", classes="balance-card")
                yield Static("Loading...", id="pm-balance", classes="balance-card")

            # Positions table
            yield Static("[bold]Positions[/]")
            yield DataTable(id="positions-table")

            # Orders table
            yield Static("[bold]Resting Orders[/]")
            yield DataTable(id="orders-table")

            # Trades table
            yield Static("[bold]Recent Trades[/]")
            yield DataTable(id="trades-table")

        yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        # Set up positions table
        pos_table = self.query_one("#positions-table", DataTable)
        pos_table.add_columns("Exchange", "Ticker", "Side", "Qty", "Avg Price")

        # Set up orders table
        ord_table = self.query_one("#orders-table", DataTable)
        ord_table.add_columns("Exchange", "Ticker", "Side", "Price", "Qty", "Status", "Order ID")

        # Set up trades table
        trades_table = self.query_one("#trades-table", DataTable)
        trades_table.add_columns("Exchange", "Ticker", "Action", "Side", "Qty", "Price", "Status")

        await self._refresh()
        self.set_interval(30, self._refresh)

    async def _refresh(self) -> None:
        try:
            portfolio = await self._services.get_portfolio()
            self._update_balances(portfolio)
            self._update_positions(portfolio)
        except Exception:
            logger.debug("Failed to refresh portfolio", exc_info=True)

        try:
            orders = await self._services.get_orders()
            self._update_orders(orders)
        except Exception:
            logger.debug("Failed to refresh orders", exc_info=True)

        try:
            trades = self._services.get_trades(limit=20)
            self._update_trades(trades)
        except Exception:
            logger.debug("Failed to refresh trades", exc_info=True)

    def _update_balances(self, portfolio: dict[str, Any]) -> None:
        kalshi = portfolio.get("kalshi", {})
        k_balance = kalshi.get("balance", {})
        k_bal = k_balance.get("balance", k_balance.get("available_balance", "?"))
        if isinstance(k_bal, int | float):
            k_bal = f"${k_bal / 100:.2f}"
        self.query_one("#kalshi-balance", Static).update(f"Kalshi: {k_bal}")

        pm = portfolio.get("polymarket", {})
        if pm:
            pm_balance = pm.get("balance", {})
            pm_bal = pm_balance.get("balance", pm_balance.get("cash_balance", "?"))
            if isinstance(pm_bal, int | float):
                pm_bal = f"${pm_bal:.2f}"
            self.query_one("#pm-balance", Static).update(f"Polymarket: {pm_bal}")
        else:
            self.query_one("#pm-balance", Static).update("Polymarket: disabled")

    def _update_positions(self, portfolio: dict[str, Any]) -> None:
        table = self.query_one("#positions-table", DataTable)
        table.clear()

        kalshi = portfolio.get("kalshi", {})
        positions = kalshi.get("positions", {}).get("market_positions", [])
        if isinstance(positions, list):
            for pos in positions:
                table.add_row(
                    "Kalshi",
                    str(pos.get("ticker", "")),
                    str(pos.get("side", "")),
                    str(pos.get("total_traded", pos.get("position", ""))),
                    str(pos.get("average_price", "")),
                )

        pm = portfolio.get("polymarket", {})
        if pm:
            pm_positions = pm.get("positions", {}).get("positions", [])
            if isinstance(pm_positions, list):
                for pos in pm_positions:
                    table.add_row(
                        "PM",
                        str(pos.get("slug", pos.get("market_slug", ""))),
                        str(pos.get("side", "")),
                        str(pos.get("quantity", pos.get("size", ""))),
                        str(pos.get("average_price", "")),
                    )

    def _update_orders(self, orders: dict[str, Any]) -> None:
        table = self.query_one("#orders-table", DataTable)
        table.clear()

        for exchange, data in orders.items():
            order_list = data.get("orders", []) if isinstance(data, dict) else []
            if isinstance(order_list, list):
                for order in order_list:
                    table.add_row(
                        exchange.upper()[:2],
                        str(order.get("ticker", order.get("market_slug", ""))),
                        str(order.get("side", "")),
                        str(order.get("price", order.get("yes_price", ""))),
                        str(order.get("remaining_count", order.get("quantity", ""))),
                        str(order.get("status", "")),
                        str(order.get("order_id", order.get("id", ""))),
                    )

    def _update_trades(self, trades: list[dict[str, Any]]) -> None:
        table = self.query_one("#trades-table", DataTable)
        table.clear()

        for trade in trades:
            table.add_row(
                str(trade.get("exchange", ""))[:2].upper(),
                str(trade.get("ticker", "")),
                str(trade.get("action", "")),
                str(trade.get("side", "")),
                str(trade.get("quantity", "")),
                str(trade.get("price_cents", "")),
                str(trade.get("status", "")),
            )

    async def action_refresh(self) -> None:
        await self._refresh()
