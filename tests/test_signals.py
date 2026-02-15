"""Tests for finance_agent.signals -- quantitative signal generators."""

from __future__ import annotations

import json

from finance_agent.signals import (
    _generate_arbitrage_signals,
    _signal,
)

# ── _signal helper ───────────────────────────────────────────────


def test_signal_caps_strength_at_1():
    s = _signal("test", "T-1", 1.5, 5.0, {"k": "v"})
    assert s["signal_strength"] == 1.0


def test_signal_rounds_values():
    s = _signal("test", "T-1", 0.33333, 5.5555, {"k": "v"})
    assert s["signal_strength"] == 0.333
    assert s["estimated_edge_pct"] == 5.56


def test_signal_passes_extras():
    s = _signal("test", "T-1", 0.5, 5.0, {}, event_ticker="EVT-1", exchange="meta")
    assert s["event_ticker"] == "EVT-1"
    assert s["exchange"] == "meta"


# ── Arbitrage ────────────────────────────────────────────────────


def test_arbitrage_no_events(db):
    assert _generate_arbitrage_signals(db) == []


def test_arbitrage_non_mutually_exclusive_skipped(db):
    db.upsert_event(
        event_ticker="EVT-1",
        mutually_exclusive=False,
        markets_json=json.dumps(
            [
                {"ticker": "M-1", "yes_bid": 60, "yes_ask": 70},
                {"ticker": "M-2", "yes_bid": 60, "yes_ask": 70},
            ]
        ),
    )
    assert _generate_arbitrage_signals(db) == []


def test_arbitrage_single_market_skipped(db):
    db.upsert_event(
        event_ticker="EVT-1",
        mutually_exclusive=True,
        markets_json=json.dumps([{"ticker": "M-1", "yes_bid": 60, "yes_ask": 70}]),
    )
    assert _generate_arbitrage_signals(db) == []


def test_arbitrage_deviation_below_threshold(db):
    # Two markets: mid = (45+55)/2=50, mid = (49+51)/2=50, sum = 100, deviation = 0
    db.upsert_event(
        event_ticker="EVT-1",
        mutually_exclusive=True,
        markets_json=json.dumps(
            [
                {"ticker": "M-1", "yes_bid": 45, "yes_ask": 55},
                {"ticker": "M-2", "yes_bid": 45, "yes_ask": 55},
            ]
        ),
    )
    assert _generate_arbitrage_signals(db) == []


def test_arbitrage_overpriced_signal(db):
    # mid1 = (50+60)/2 = 55, mid2 = (50+60)/2 = 55, sum = 110, deviation = 10
    db.upsert_event(
        event_ticker="EVT-1",
        mutually_exclusive=True,
        markets_json=json.dumps(
            [
                {"ticker": "M-1", "yes_bid": 50, "yes_ask": 60},
                {"ticker": "M-2", "yes_bid": 50, "yes_ask": 60},
            ]
        ),
    )
    signals = _generate_arbitrage_signals(db)
    assert len(signals) == 1
    assert signals[0]["details_json"]["direction"] == "overpriced"
    # strength = (deviation/10) * liquidity_factor; with no snapshots, liquidity_factor = 0.1
    assert signals[0]["signal_strength"] > 0
    # Fee-adjusted: raw 10% minus Kalshi P(1-P) fees ≈ 6.52%
    assert 5.0 < signals[0]["estimated_edge_pct"] < 10.0


def test_arbitrage_underpriced_signal(db):
    # mid1 = (15+25)/2 = 20, mid2 = (30+40)/2 = 35, sum = 55, deviation = 45
    db.upsert_event(
        event_ticker="EVT-2",
        mutually_exclusive=True,
        markets_json=json.dumps(
            [
                {"ticker": "M-1", "yes_bid": 15, "yes_ask": 25},
                {"ticker": "M-2", "yes_bid": 30, "yes_ask": 40},
            ]
        ),
    )
    signals = _generate_arbitrage_signals(db)
    assert len(signals) == 1
    assert signals[0]["details_json"]["direction"] == "underpriced"
