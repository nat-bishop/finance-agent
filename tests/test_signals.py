"""Tests for finance_agent.signals -- quantitative signal generators."""

from __future__ import annotations

import json

from finance_agent.signals import (
    _generate_arbitrage_signals,
    _generate_cross_platform_signals,
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
    assert signals[0]["signal_strength"] == 1.0  # 10/10 = 1.0
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


# ── Cross-platform candidate ────────────────────────────────────


def test_cross_platform_no_data(db):
    assert _generate_cross_platform_signals(db) == []


def test_cross_platform_matching_titles(db, sample_market_snapshot):
    # Insert Kalshi and Polymarket markets with similar titles and a price gap
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                ticker="K-PRES-YES",
                exchange="kalshi",
                title="Will Biden win the election?",
                mid_price_cents=45,
                volume_24h=500,
            ),
            sample_market_snapshot(
                ticker="pm-pres-yes",
                exchange="polymarket",
                title="Will Biden win the election?",
                mid_price_cents=52,
                volume_24h=300,
            ),
        ]
    )
    signals = _generate_cross_platform_signals(db)
    assert len(signals) == 1
    assert signals[0]["scan_type"] == "cross_platform_candidate"
    assert signals[0]["details_json"]["price_gap_cents"] == 7


def test_cross_platform_small_gap_skipped(db, sample_market_snapshot):
    # Same title but gap < 3 cents
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                ticker="K-1",
                exchange="kalshi",
                title="Will it rain tomorrow?",
                mid_price_cents=50,
                volume_24h=100,
            ),
            sample_market_snapshot(
                ticker="PM-1",
                exchange="polymarket",
                title="Will it rain tomorrow?",
                mid_price_cents=51,
                volume_24h=100,
            ),
        ]
    )
    assert _generate_cross_platform_signals(db) == []


def test_cross_platform_dissimilar_titles_skipped(db, sample_market_snapshot):
    # Completely different titles
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                ticker="K-1",
                exchange="kalshi",
                title="Will GDP grow in Q4?",
                mid_price_cents=40,
                volume_24h=100,
            ),
            sample_market_snapshot(
                ticker="PM-1",
                exchange="polymarket",
                title="Will Bitcoin hit $100k?",
                mid_price_cents=60,
                volume_24h=100,
            ),
        ]
    )
    assert _generate_cross_platform_signals(db) == []
