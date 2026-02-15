"""Tests for finance_agent.signals -- quantitative signal generators."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from finance_agent.signals import (
    _generate_arbitrage_signals,
    _generate_calibration_signals,
    _generate_momentum_signals,
    _generate_theta_decay_signals,
    _generate_wide_spread_signals,
    _signal,
)


def _recent_iso(hours_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


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
    assert signals[0]["estimated_edge_pct"] == 10.0


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


# ── Wide spread ──────────────────────────────────────────────────


def test_wide_spread_no_data(db):
    assert _generate_wide_spread_signals(db) == []


def test_wide_spread_narrow_spread_skipped(db, sample_market_snapshot):
    db.insert_market_snapshots(
        [sample_market_snapshot(spread_cents=3, yes_bid=48, yes_ask=51, volume=100)]
    )
    assert _generate_wide_spread_signals(db) == []


def test_wide_spread_zero_volume_skipped(db, sample_market_snapshot):
    db.insert_market_snapshots([sample_market_snapshot(spread_cents=10, volume=0, volume_24h=0)])
    assert _generate_wide_spread_signals(db) == []


def test_wide_spread_low_liquidity_skipped(db, sample_market_snapshot):
    # volume_24h=1, spread=6 => liq_score = (1/100)*(6/20) = 0.003 < 0.1
    db.insert_market_snapshots([sample_market_snapshot(spread_cents=6, volume=1, volume_24h=1)])
    assert _generate_wide_spread_signals(db) == []


def test_wide_spread_valid_signal(db, sample_market_snapshot):
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                spread_cents=10,
                volume=100,
                volume_24h=500,
                yes_bid=45,
                yes_ask=55,
                mid_price_cents=50,
            )
        ]
    )
    signals = _generate_wide_spread_signals(db)
    assert len(signals) == 1
    assert signals[0]["estimated_edge_pct"] == 5.0  # spread/2


# ── Theta decay ──────────────────────────────────────────────────


def test_theta_decay_not_near_expiry(db, sample_market_snapshot):
    db.insert_market_snapshots(
        [sample_market_snapshot(days_to_expiration=10.0, mid_price_cents=50)]
    )
    assert _generate_theta_decay_signals(db) == []


def test_theta_decay_mid_outside_range(db, sample_market_snapshot):
    db.insert_market_snapshots(
        [sample_market_snapshot(days_to_expiration=1.0, mid_price_cents=90)]
    )
    assert _generate_theta_decay_signals(db) == []


def test_theta_decay_low_strength_skipped(db, sample_market_snapshot):
    # dte=2.9, mid=51 => dist_from_50 = 1/50 = 0.02, strength = (1-2.9/3)*0.02*2 ≈ 0.001
    db.insert_market_snapshots(
        [sample_market_snapshot(days_to_expiration=2.9, mid_price_cents=51)]
    )
    assert _generate_theta_decay_signals(db) == []


def test_theta_decay_valid_signal(db, sample_market_snapshot):
    # dte=0.5, mid=30 => dist_from_50 = 20/50 = 0.4
    # strength = (1-0.5/3)*0.4*2 = 0.833*0.4*2 = 0.667
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                days_to_expiration=0.5,
                mid_price_cents=30,
                yes_bid=25,
                yes_ask=35,
                exchange="kalshi",
            )
        ]
    )
    signals = _generate_theta_decay_signals(db)
    assert len(signals) == 1
    assert signals[0]["scan_type"] == "theta_decay"
    assert signals[0]["exchange"] == "kalshi"
    assert signals[0]["signal_strength"] > 0.2


# ── Momentum ─────────────────────────────────────────────────────


def test_momentum_insufficient_snapshots(db, sample_market_snapshot):
    # Only 2 snapshots
    for i in range(2):
        db.insert_market_snapshots(
            [
                sample_market_snapshot(
                    mid_price_cents=50 + i * 5,
                    captured_at=_recent_iso(hours_ago=i),
                )
            ]
        )
    assert _generate_momentum_signals(db) == []


def test_momentum_small_move_skipped(db, sample_market_snapshot):
    # 3 snapshots: 50, 51, 52 => move = 2 < 5
    for i in range(3):
        db.insert_market_snapshots(
            [
                sample_market_snapshot(
                    mid_price_cents=50 + i,
                    captured_at=_recent_iso(hours_ago=3 - i),
                )
            ]
        )
    assert _generate_momentum_signals(db) == []


def test_momentum_inconsistent_direction_skipped(db, sample_market_snapshot):
    # 4 snapshots: 50, 58, 48, 56 => move = 6, but direction flips
    prices = [50, 58, 48, 56]
    for i, price in enumerate(prices):
        db.insert_market_snapshots(
            [
                sample_market_snapshot(
                    mid_price_cents=price,
                    captured_at=_recent_iso(hours_ago=4 - i),
                )
            ]
        )
    _generate_momentum_signals(db)
    # Consistency: moves are +8,-10,+8. Overall move=6 (up).
    # same_dir for up: +8 yes, -10 no, +8 yes = 2/3 = 0.67 >= 0.6 (borderline pass)


def test_momentum_valid_up_signal(db, sample_market_snapshot):
    # 4 snapshots: 50, 54, 57, 62 => move = 12, all positive
    prices = [50, 54, 57, 62]
    for i, price in enumerate(prices):
        db.insert_market_snapshots(
            [
                sample_market_snapshot(
                    mid_price_cents=price,
                    captured_at=_recent_iso(hours_ago=4 - i),
                )
            ]
        )
    signals = _generate_momentum_signals(db)
    assert len(signals) == 1
    assert signals[0]["details_json"]["direction"] == "up"
    assert signals[0]["details_json"]["move_cents"] == 12


def test_momentum_valid_down_signal(db, sample_market_snapshot):
    prices = [60, 56, 53, 48]
    for i, price in enumerate(prices):
        db.insert_market_snapshots(
            [
                sample_market_snapshot(
                    mid_price_cents=price,
                    captured_at=_recent_iso(hours_ago=4 - i),
                )
            ]
        )
    signals = _generate_momentum_signals(db)
    assert len(signals) == 1
    assert signals[0]["details_json"]["direction"] == "down"


# ── Calibration ──────────────────────────────────────────────────


def test_calibration_insufficient_predictions(db):
    # Only 5 resolved
    for _ in range(5):
        pid = db.log_prediction("M-1", 0.5)
        db.resolve_prediction(pid, 1)
    assert _generate_calibration_signals(db) == []


def test_calibration_valid_signal(db):
    for i in range(12):
        pred = 0.5 + (i % 3) * 0.1
        outcome = 1 if i % 2 == 0 else 0
        pid = db.log_prediction("M-1", pred)
        db.resolve_prediction(pid, outcome)
    signals = _generate_calibration_signals(db)
    assert len(signals) == 1
    assert signals[0]["ticker"] == "META_CALIBRATION"
    assert signals[0]["exchange"] == "meta"
    assert signals[0]["scan_type"] == "calibration"


def test_calibration_perfect_predictions(db):
    # 10 perfect predictions => low Brier => high strength
    for i in range(10):
        pred = 0.9 if i < 5 else 0.1
        outcome = 1 if i < 5 else 0
        pid = db.log_prediction("M-1", pred)
        db.resolve_prediction(pid, outcome)
    signals = _generate_calibration_signals(db)
    assert len(signals) == 1
    brier = signals[0]["details_json"]["brier_score"]
    assert brier < 0.1  # low Brier = good
    assert signals[0]["signal_strength"] > 0.5


def test_calibration_has_buckets(db):
    # Predictions in different ranges
    data = [
        (0.1, 0),
        (0.15, 0),
        (0.3, 0),
        (0.35, 1),
        (0.55, 1),
        (0.6, 0),
        (0.75, 1),
        (0.8, 1),
        (0.9, 1),
        (0.95, 1),
    ]
    for pred, outcome in data:
        pid = db.log_prediction("M-1", pred)
        db.resolve_prediction(pid, outcome)
    signals = _generate_calibration_signals(db)
    assert len(signals) == 1
    buckets = signals[0]["details_json"]["buckets"]
    assert len(buckets) > 0
