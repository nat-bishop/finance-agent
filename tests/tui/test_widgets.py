"""Smoke tests for TUI widgets -- mounting and basic rendering."""

from __future__ import annotations

from textual.app import App, ComposeResult

from finance_agent.tui.widgets.portfolio_panel import PortfolioPanel
from finance_agent.tui.widgets.rec_card import RecCard
from finance_agent.tui.widgets.rec_list import RecList
from finance_agent.tui.widgets.status_bar import StatusBar

# ── Helpers ───────────────────────────────────────────────────────

SAMPLE_GROUP = {
    "id": 42,
    "legs": [
        {
            "exchange": "kalshi",
            "action": "buy",
            "side": "yes",
            "price_cents": 45,
            "quantity": 10,
        },
    ],
    "estimated_edge_pct": 7.5,
    "thesis": "Test thesis for card display",
    "expires_at": "2027-12-31T00:00:00+00:00",
}


# ── StatusBar ─────────────────────────────────────────────────────


class StatusBarApp(App):
    def compose(self) -> ComposeResult:
        yield StatusBar(id="bar")


async def test_status_bar_defaults():
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one("#bar", StatusBar)
        text = bar.render()
        assert "Session:" in text
        assert "$0.0000" in text


async def test_status_bar_reactive_updates():
    async with StatusBarApp().run_test() as pilot:
        bar = pilot.app.query_one("#bar", StatusBar)
        bar.session_id = "test1234"
        bar.total_cost = 0.5678
        bar.rec_count = 3
        text = bar.render()
        assert "test1234" in text
        assert "0.5678" in text
        assert "3" in text


# ── PortfolioPanel ────────────────────────────────────────────────


class PortfolioPanelApp(App):
    def compose(self) -> ComposeResult:
        yield PortfolioPanel(id="pp")


async def test_portfolio_panel_initial():
    async with PortfolioPanelApp().run_test() as pilot:
        pp = pilot.app.query_one("#pp", PortfolioPanel)
        content = pp.query_one("#portfolio-content")
        # Initial state should show loading text
        assert content is not None


async def test_portfolio_panel_update():
    async with PortfolioPanelApp().run_test() as pilot:
        pp = pilot.app.query_one("#pp", PortfolioPanel)
        pp.update_data(
            {
                "kalshi": {
                    "balance": {"balance": 5000},
                    "positions": {"market_positions": [{"ticker": "T-1"}]},
                },
            }
        )
        await pilot.pause()


# ── RecCard ───────────────────────────────────────────────────────


class RecCardApp(App):
    def compose(self) -> ComposeResult:
        yield RecCard(SAMPLE_GROUP)


async def test_rec_card_renders():
    async with RecCardApp().run_test() as pilot:
        cards = list(pilot.app.query(RecCard))
        assert len(cards) == 1


async def test_rec_card_has_buttons():
    async with RecCardApp().run_test() as pilot:
        buttons = list(pilot.app.query("Button"))
        assert len(buttons) == 2
        labels = [str(b.label) for b in buttons]
        assert any("Execute" in label for label in labels)
        assert any("Reject" in label for label in labels)


# ── RecList ───────────────────────────────────────────────────────


class RecListApp(App):
    def compose(self) -> ComposeResult:
        yield RecList(id="rl")


async def test_rec_list_empty():
    async with RecListApp().run_test() as pilot:
        rl = pilot.app.query_one("#rl", RecList)
        empty = rl.query_one("#rec-empty")
        assert empty.display is True


async def test_rec_list_update_with_groups():
    async with RecListApp().run_test() as pilot:
        rl = pilot.app.query_one("#rl", RecList)
        rl.update_recs([SAMPLE_GROUP])
        await pilot.pause()
        cards = list(rl.query(RecCard))
        assert len(cards) == 1
        empty = rl.query_one("#rec-empty")
        assert empty.display is False


async def test_rec_list_clear():
    async with RecListApp().run_test() as pilot:
        rl = pilot.app.query_one("#rl", RecList)
        rl.update_recs([SAMPLE_GROUP])
        await pilot.pause()
        rl.update_recs([])
        await pilot.pause()
        empty = rl.query_one("#rec-empty")
        assert empty.display is True
        cards = list(rl.query(RecCard))
        assert len(cards) == 0
