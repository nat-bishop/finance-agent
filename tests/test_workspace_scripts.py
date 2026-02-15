"""Tests for workspace/lib/ scripts -- pure utility functions."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _import_script(name: str):
    """Import a workspace script by name."""
    script_path = Path(__file__).parent.parent / "workspace" / "lib" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(script_path))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


normalize = _import_script("normalize_prices")
kelly_mod = _import_script("kelly_size")
match_mod = _import_script("match_markets")


# ── normalize_prices.compare ─────────────────────────────────────
# New API: compare(kalshi_cents, poly_cents, contracts=100, maker=False)
# Returns nested structure with 'scenarios' dict, not flat keys.


def test_compare_kalshi_higher():
    result = normalize.compare(60, 52)
    assert result["direction"] == "buy_poly_sell_kalshi"
    assert result["gross_edge_pct"] == 8.0


def test_compare_poly_higher():
    result = normalize.compare(40, 52)
    assert result["direction"] == "buy_kalshi_sell_poly"
    assert result["gross_edge_pct"] == 12.0


def test_compare_fees_reduce_edge():
    result = normalize.compare(60, 52)
    best = result["scenarios"]["legin_kalshi_maker"]
    assert best["net_edge_pct"] < result["gross_edge_pct"]
    assert best["total_fees"] > 0


def test_compare_unprofitable():
    # 1 cent difference at 50/51c — fees eat the edge
    result = normalize.compare(51, 50)
    both_taker = result["scenarios"]["both_taker"]
    assert both_taker["profitable"] is False


def test_compare_equal_prices():
    result = normalize.compare(50, 50)
    assert result["gross_edge_pct"] == 0.0


def test_compare_scenarios_structure():
    result = normalize.compare(60, 50)
    assert "scenarios" in result
    assert "legin_kalshi_maker" in result["scenarios"]
    assert "legin_poly_maker" in result["scenarios"]
    assert "both_taker" in result["scenarios"]
    for scenario in result["scenarios"].values():
        assert "net_edge_usd" in scenario
        assert "net_edge_pct" in scenario
        assert "profitable" in scenario


# ── kelly_size.kelly ─────────────────────────────────────────────


def test_kelly_positive_edge():
    result = kelly_mod.kelly(0.10, 1.0, 500, fraction=0.25)
    assert result["bet_size_usd"] > 0
    assert result["full_kelly"] > 0
    assert result["fractional_kelly"] > 0


def test_kelly_zero_edge():
    result = kelly_mod.kelly(0.0, 1.0, 500)
    assert result["bet_size_usd"] == 0


def test_kelly_negative_edge():
    result = kelly_mod.kelly(-0.10, 1.0, 500)
    assert result["bet_size_usd"] == 0
    assert result["full_kelly"] < 0


def test_kelly_fraction_reduces_bet():
    full = kelly_mod.kelly(0.10, 1.0, 500, fraction=1.0)
    quarter = kelly_mod.kelly(0.10, 1.0, 500, fraction=0.25)
    assert quarter["bet_size_usd"] < full["bet_size_usd"]


def test_kelly_risk_of_ruin_bounded():
    result = kelly_mod.kelly(0.10, 1.0, 500, fraction=0.25)
    assert 0 <= result["risk_of_ruin"] <= 1


# ── match_markets._norm ──────────────────────────────────────────


def test_norm_removes_stopwords_and_punctuation():
    result = match_mod._norm("Will the price be high?")
    assert "will" not in result
    assert "the" not in result
    assert "?" not in result
    assert "price" in result
    assert "high" in result


def test_norm_lowercases():
    assert match_mod._norm("HELLO World") == "hello world"


# ── match_markets.match ──────────────────────────────────────────


def test_match_identical_titles():
    kalshi = [{"ticker": "K1", "title": "Will Trump win the election?"}]
    poly = [{"ticker": "P1", "title": "Will Trump win the election?"}]
    results = match_mod.match(kalshi, poly)
    assert len(results) == 1
    assert results[0]["similarity"] == 1.0
    assert results[0]["needs_verification"] is False


def test_match_below_threshold():
    kalshi = [{"ticker": "K1", "title": "Will it rain tomorrow?"}]
    poly = [{"ticker": "P1", "title": "Fed interest rate decision March"}]
    results = match_mod.match(kalshi, poly, threshold=0.7)
    assert len(results) == 0


def test_match_empty_lists():
    assert match_mod.match([], []) == []
    assert match_mod.match([{"ticker": "K1", "title": "Test"}], []) == []
    assert match_mod.match([], [{"ticker": "P1", "title": "Test"}]) == []


def test_match_needs_verification():
    kalshi = [{"ticker": "K1", "title": "Bitcoin price 100k by December"}]
    poly = [{"ticker": "P1", "title": "Bitcoin to hit 100k before December"}]
    results = match_mod.match(kalshi, poly, threshold=0.5)
    if results and results[0]["similarity"] < 0.9:
        assert results[0]["needs_verification"] is True
