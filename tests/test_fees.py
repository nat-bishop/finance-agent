"""Tests for finance_agent.fees — P&L computation and depth assessment."""

from __future__ import annotations

import json

from finance_agent.fees import assess_depth_concern, compute_hypothetical_pnl

# ── Bracket P&L ─────────────────────────────────────────────────


def test_pnl_bracket_positive():
    """3-leg bracket at 30c each (sum=90c), qty=10 → positive P&L."""
    group = {
        "strategy": "bracket",
        "legs": [
            {"price_cents": 30, "quantity": 10, "is_maker": False, "side": "yes"},
            {"price_cents": 30, "quantity": 10, "is_maker": False, "side": "yes"},
            {"price_cents": 30, "quantity": 10, "is_maker": False, "side": "yes"},
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # Payout = 100 * 10 / 100 = $10.00
    # Cost = 90 * 10 / 100 = $9.00
    # Gross = $1.00, minus fees
    assert pnl > 0
    assert pnl < 1.0  # Gross is $1.00, fees reduce it


def test_pnl_bracket_negative():
    """Bracket with sum > 100c → negative P&L."""
    group = {
        "strategy": "bracket",
        "legs": [
            {"price_cents": 60, "quantity": 5, "is_maker": False, "side": "yes"},
            {"price_cents": 60, "quantity": 5, "is_maker": False, "side": "yes"},
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # Cost = 120 * 5 / 100 = $6.00, payout = 100 * 5 / 100 = $5.00
    assert pnl < 0


def test_pnl_bracket_empty_legs():
    group = {"strategy": "bracket", "legs": []}
    assert compute_hypothetical_pnl(group) == 0.0


# ── Manual P&L ──────────────────────────────────────────────────


def test_pnl_manual_buy_yes_win():
    """BUY YES at 40c, settles at 100c → profit."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 40,
                "quantity": 10,
                "action": "buy",
                "side": "yes",
                "is_maker": False,
                "settlement_value": 100,
            },
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # Gross = (100 - 40) * 10 / 100 = $6.00, minus fees
    assert pnl > 5.0


def test_pnl_manual_buy_yes_lose():
    """BUY YES at 40c, settles at 0c → loss."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 40,
                "quantity": 10,
                "action": "buy",
                "side": "yes",
                "is_maker": False,
                "settlement_value": 0,
            },
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # Gross = (0 - 40) * 10 / 100 = -$4.00, minus fees
    assert pnl < -4.0


def test_pnl_manual_sell_yes_win():
    """SELL YES at 60c, YES settles at 100c → loss (sold too cheap)."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 60,
                "quantity": 10,
                "action": "sell",
                "side": "yes",
                "is_maker": False,
                "settlement_value": 100,
            },
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # Gross = (60 - 100) * 10 / 100 = -$4.00
    assert pnl < -4.0


def test_pnl_manual_sell_yes_lose():
    """SELL YES at 60c, YES settles at 0c → profit."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 60,
                "quantity": 10,
                "action": "sell",
                "side": "yes",
                "is_maker": False,
                "settlement_value": 0,
            },
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # Gross = (60 - 0) * 10 / 100 = $6.00
    assert pnl > 5.0


def test_pnl_manual_buy_no_win():
    """BUY NO at 40c, YES settles at 0 (NO won) → profit."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 40,
                "quantity": 10,
                "action": "buy",
                "side": "no",
                "is_maker": False,
                "settlement_value": 0,  # YES=0 means NO=100
            },
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # effective_settlement for NO = 100 - 0 = 100
    # Gross = (100 - 40) * 10 / 100 = $6.00
    assert pnl > 5.0


def test_pnl_manual_buy_no_lose():
    """BUY NO at 40c, YES settles at 100 (NO lost) → loss."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 40,
                "quantity": 10,
                "action": "buy",
                "side": "no",
                "is_maker": False,
                "settlement_value": 100,  # YES=100 means NO=0
            },
        ],
    }
    pnl = compute_hypothetical_pnl(group)
    # effective_settlement for NO = 100 - 100 = 0
    # Gross = (0 - 40) * 10 / 100 = -$4.00
    assert pnl < -4.0


def test_pnl_manual_unsettled_leg_skipped():
    """Legs with settlement_value=None are skipped in P&L calculation."""
    group = {
        "strategy": "manual",
        "legs": [
            {
                "price_cents": 40,
                "quantity": 10,
                "action": "buy",
                "side": "yes",
                "is_maker": False,
                "settlement_value": None,
            },
        ],
    }
    assert compute_hypothetical_pnl(group) == 0.0


# ── Depth concern ───────────────────────────────────────────────


def test_assess_depth_no_warning():
    leg = {
        "quantity": 10,
        "side": "yes",
        "orderbook_snapshot_json": json.dumps({"yes_depth": 20, "no_depth": 15}),
    }
    assert assess_depth_concern(leg) is None


def test_assess_depth_warning():
    leg = {
        "quantity": 10,
        "side": "yes",
        "orderbook_snapshot_json": json.dumps({"yes_depth": 5, "no_depth": 15}),
    }
    result = assess_depth_concern(leg)
    assert result is not None
    assert "5" in result
    assert "10" in result


def test_assess_depth_no_snapshot():
    leg = {"quantity": 10, "side": "yes", "orderbook_snapshot_json": None}
    assert assess_depth_concern(leg) is None


def test_assess_depth_no_side():
    leg = {
        "quantity": 10,
        "side": "no",
        "orderbook_snapshot_json": json.dumps({"yes_depth": 20, "no_depth": 3}),
    }
    result = assess_depth_concern(leg)
    assert result is not None
    assert "no" in result
