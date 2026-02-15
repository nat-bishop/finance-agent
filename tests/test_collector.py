"""Tests for finance_agent.collector -- data collection pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finance_agent.collector import (
    _as_list,
    _collect_markets_by_status,
    _compute_derived,
    _compute_derived_polymarket,
    _generate_market_listings,
    _parse_days_to_expiry,
    collect_events,
    collect_polymarket_events,
    collect_polymarket_markets,
)

# ── _parse_days_to_expiry ────────────────────────────────────────


def test_parse_days_none():
    assert _parse_days_to_expiry(None) is None


def test_parse_days_empty_string():
    assert _parse_days_to_expiry("") is None


def test_parse_days_iso_string():
    future = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    result = _parse_days_to_expiry(future)
    assert result is not None
    assert 4.9 < result < 5.1


def test_parse_days_z_suffix():
    future = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = _parse_days_to_expiry(future)
    assert result is not None
    assert 1.9 < result < 2.1


def test_parse_days_unix_timestamp():
    future_ts = (datetime.now(UTC) + timedelta(days=3)).timestamp()
    result = _parse_days_to_expiry(future_ts)
    assert result is not None
    assert 2.9 < result < 3.1


def test_parse_days_past_date():
    past = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    result = _parse_days_to_expiry(past)
    assert result == 0.0


def test_parse_days_invalid_string():
    assert _parse_days_to_expiry("not-a-date") is None


@pytest.mark.parametrize("bad_input", [[], {}, object()])
def test_parse_days_non_parseable(bad_input):
    assert _parse_days_to_expiry(bad_input) is None


# ── _compute_derived (Kalshi) ────────────────────────────────────


def test_compute_derived_full_data():
    now = datetime.now(UTC).isoformat()
    market = {
        "ticker": "K-MKT-1",
        "event_ticker": "EVT-1",
        "series_ticker": "SER-1",
        "title": "Test Market",
        "category": "Politics",
        "status": "open",
        "yes_bid": 45,
        "yes_ask": 55,
        "no_bid": 45,
        "no_ask": 55,
        "last_price": 50,
        "volume": 1000,
        "volume_24h": 500,
        "open_interest": 200,
        "close_time": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        "settlement_value": None,
    }
    result = _compute_derived(market, now)
    assert result["spread_cents"] == 10
    assert result["mid_price_cents"] == 50
    assert result["implied_probability"] == 0.5
    assert result["exchange"] == "kalshi"


def test_compute_derived_missing_bid():
    now = datetime.now(UTC).isoformat()
    market = {"yes_bid": 0, "yes_ask": 55, "ticker": "K-1"}
    result = _compute_derived(market, now)
    assert result["spread_cents"] is None
    assert result["mid_price_cents"] is None


def test_compute_derived_settlement_value():
    now = datetime.now(UTC).isoformat()
    market = {"ticker": "K-1", "yes_bid": 45, "yes_ask": 55, "settlement_value": "yes"}
    result = _compute_derived(market, now)
    assert result["settlement_value"] == "yes"


# ── _compute_derived_polymarket ──────────────────────────────────


def test_compute_derived_polymarket_usd_to_cents():
    now = datetime.now(UTC).isoformat()
    market = {
        "slug": "test-slug",
        "title": "Test PM",
        "yes_price": 0.55,
        "active": True,
        "volume": 1000,
    }
    result = _compute_derived_polymarket(market, now)
    assert result["mid_price_cents"] == 55
    assert result["ticker"] == "test-slug"
    assert result["status"] == "open"
    assert result["exchange"] == "polymarket"


def test_compute_derived_polymarket_camelcase_keys():
    now = datetime.now(UTC).isoformat()
    market = {
        "slug": "test",
        "title": "Test",
        "yes_price": 0.50,
        "bestBid": 0.48,
        "bestAsk": 0.52,
        "active": True,
    }
    result = _compute_derived_polymarket(market, now)
    assert result["yes_bid"] == 48
    assert result["yes_ask"] == 52
    assert result["spread_cents"] == 4
    assert result["mid_price_cents"] == 50


def test_compute_derived_polymarket_snake_case_keys():
    now = datetime.now(UTC).isoformat()
    market = {
        "slug": "test",
        "title": "Test",
        "yes_price": 0.50,
        "best_bid": 0.48,
        "best_ask": 0.52,
        "active": True,
    }
    result = _compute_derived_polymarket(market, now)
    assert result["yes_bid"] == 48
    assert result["yes_ask"] == 52


def test_compute_derived_polymarket_closed_status():
    now = datetime.now(UTC).isoformat()
    market = {"slug": "test", "title": "Test", "active": False}
    result = _compute_derived_polymarket(market, now)
    assert result["status"] == "closed"


# ── _as_list ─────────────────────────────────────────────────────


def test_as_list_list_input():
    assert _as_list([1, 2, 3]) == [1, 2, 3]


def test_as_list_dict_with_key():
    assert _as_list({"markets": [1, 2]}, "markets") == [1, 2]


def test_as_list_fallback_key():
    assert _as_list({"data": [1]}, "markets", "data") == [1]


def test_as_list_no_matching_key():
    assert _as_list({"other": [1]}, "markets") == []


# ── _collect_markets_by_status ───────────────────────────────────


def test_collect_markets_pagination(db, mock_kalshi):
    # First call returns cursor, second returns no cursor
    mock_kalshi.search_markets.side_effect = [
        {
            "markets": [
                {"ticker": f"T-{i}", "yes_bid": 45, "yes_ask": 55, "status": "open"}
                for i in range(3)
            ],
            "cursor": "page2",
        },
        {
            "markets": [
                {"ticker": f"T-{i + 3}", "yes_bid": 45, "yes_ask": 55, "status": "open"}
                for i in range(2)
            ],
            "cursor": None,
        },
    ]
    total = _collect_markets_by_status(mock_kalshi, db, "open", "test")
    assert total == 5
    assert mock_kalshi.search_markets.call_count == 2


def test_collect_markets_max_total(db, mock_kalshi):
    mock_kalshi.search_markets.return_value = {
        "markets": [
            {"ticker": f"T-{i}", "yes_bid": 45, "yes_ask": 55, "status": "settled"}
            for i in range(200)
        ],
        "cursor": "more",
    }
    total = _collect_markets_by_status(mock_kalshi, db, "settled", "test", max_total=200)
    assert total <= 200


# ── collect_events ───────────────────────────────────────────────


def test_collect_events(db, mock_kalshi):
    mock_kalshi.get_events.side_effect = [
        {
            "events": [
                {
                    "event_ticker": "EVT-1",
                    "title": "Test Event",
                    "category": "Politics",
                    "mutually_exclusive": True,
                    "markets": [
                        {
                            "ticker": "M-1",
                            "title": "Market 1",
                            "yes_bid": 45,
                            "yes_ask": 55,
                            "status": "open",
                        },
                    ],
                },
            ],
            "cursor": None,
        },
    ]
    total = collect_events(mock_kalshi, db)
    assert total == 1
    events = db.get_all_events()
    matching = [e for e in events if e["event_ticker"] == "EVT-1"]
    assert matching[0]["title"] == "Test Event"


# ── collect_polymarket_markets ───────────────────────────────────


def test_collect_polymarket_markets(db, mock_polymarket):
    mock_polymarket.search_markets.side_effect = [
        {
            "markets": [
                {"slug": "pm-1", "title": "PM Market", "yes_price": 0.55, "active": True},
            ],
        },
        {"markets": []},
    ]
    total = collect_polymarket_markets(mock_polymarket, db)
    assert total == 1


# ── collect_polymarket_events ────────────────────────────────────


def test_collect_polymarket_events(db, mock_polymarket):
    mock_polymarket.list_events.side_effect = [
        {
            "events": [
                {
                    "slug": "evt-1",
                    "title": "PM Event",
                    "category": "Sports",
                    "markets": [
                        {"slug": "m-1", "title": "Market 1", "yes_price": 0.50, "active": True},
                    ],
                },
            ],
        },
        {"events": []},
    ]
    total = collect_polymarket_events(mock_polymarket, db)
    assert total == 1


# ── _generate_market_listings ────────────────────────────────────


def test_generate_market_listings(db, sample_market_snapshot, tmp_path):
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                ticker="K-1", exchange="kalshi", category="Politics", mid_price_cents=50
            ),
            sample_market_snapshot(
                ticker="P-1", exchange="polymarket", category="Sports", mid_price_cents=60
            ),
        ]
    )
    output = tmp_path / "active_markets.md"
    _generate_market_listings(db, str(output))
    content = output.read_text()
    assert "# Active Markets" in content
    assert "Politics" in content
    assert "Sports" in content
    assert "K-1" in content
    assert "P-1" in content
