"""Tests for finance_agent.database -- AgentDatabase (ORM-backed)."""

from __future__ import annotations

from datetime import datetime

import pytest
from helpers import get_row, raw_select

from finance_agent.models import Event, Session

# ── Schema / Init ────────────────────────────────────────────────


def test_db_creates_all_tables(db):
    rows = raw_select(db, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    names = {r["name"] for r in rows}
    expected = {
        "market_snapshots",
        "events",
        "trades",
        "portfolio_snapshots",
        "sessions",
        "watchlist",
        "recommendation_groups",
        "recommendation_legs",
        "alembic_version",
    }
    assert expected.issubset(names)


def test_db_wal_mode(db):
    rows = raw_select(db, "SELECT * FROM pragma_journal_mode")
    assert rows[0][next(iter(rows[0].keys()))] == "wal"


def test_db_foreign_keys_enabled(db):
    rows = raw_select(db, "SELECT * FROM pragma_foreign_keys")
    assert rows[0][next(iter(rows[0].keys()))] == 1


# ── Sessions ─────────────────────────────────────────────────────


def test_create_session_returns_8_char_id(db):
    sid = db.create_session()
    assert isinstance(sid, str)
    assert len(sid) == 8


def test_create_session_stores_started_at(db):
    sid = db.create_session()
    row = get_row(db, Session, sid)
    assert row["started_at"] is not None


def test_end_session_sets_fields(db, session_id):
    db.end_session(
        session_id,
        summary="Test summary",
        trades_placed=5,
        recommendations_made=3,
        pnl_usd=12.50,
    )
    r = get_row(db, Session, session_id)
    assert r["ended_at"] is not None
    assert r["summary"] == "Test summary"
    assert r["trades_placed"] == 5
    assert r["recommendations_made"] == 3
    assert r["pnl_usd"] == 12.50


def test_get_sessions(db):
    db.create_session()
    db.create_session()
    sessions = db.get_sessions()
    assert len(sessions) == 2


# ── Trades ───────────────────────────────────────────────────────


def test_log_trade_returns_rowid(db, session_id):
    row_id = db.log_trade(session_id, "TICKER-X", "buy", "yes", 10)
    assert isinstance(row_id, int)
    assert row_id > 0


def test_log_trade_stores_all_fields(db, session_id):
    db.log_trade(
        session_id,
        "TICKER-X",
        "buy",
        "yes",
        10,
        price_cents=45,
        order_type="limit",
        order_id="ORD-1",
        status="placed",
        result_json='{"ok": true}',
        exchange="polymarket",
    )
    trades = db.get_trades()
    r = next(t for t in trades if t["ticker"] == "TICKER-X")
    assert r["exchange"] == "polymarket"
    assert r["price_cents"] == 45
    assert r["order_id"] == "ORD-1"
    assert r["status"] == "placed"


@pytest.mark.parametrize("exchange", ["kalshi", "polymarket"])
def test_log_trade_exchange(db, session_id, exchange):
    db.log_trade(session_id, "T-1", "buy", "yes", 1, exchange=exchange)
    trades = db.get_trades(exchange=exchange)
    assert trades[0]["exchange"] == exchange


def test_get_trades_with_filter(db, session_id):
    db.log_trade(session_id, "T-1", "buy", "yes", 10, exchange="kalshi")
    db.log_trade(session_id, "T-2", "sell", "no", 5, exchange="polymarket")
    trades = db.get_trades(exchange="kalshi")
    assert len(trades) == 1
    assert trades[0]["ticker"] == "T-1"


# ── Recommendation Groups ────────────────────────────────────────


def test_log_recommendation_group_returns_id(db, session_id):
    group_id, expires_at = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test thesis",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Test Leg",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    assert isinstance(group_id, int)
    assert group_id > 0
    assert expires_at is not None


def test_log_recommendation_group_with_multiple_legs(db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Arb opportunity",
        estimated_edge_pct=7.0,
        equivalence_notes="Same event",
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Leg 1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            },
            {
                "exchange": "polymarket",
                "market_id": "PM-1",
                "market_title": "Leg 2",
                "action": "sell",
                "side": "yes",
                "quantity": 10,
                "price_cents": 52,
            },
        ],
    )
    group = db.get_group(group_id)
    assert group is not None
    assert len(group["legs"]) == 2
    assert group["legs"][0]["leg_index"] == 0
    assert group["legs"][1]["leg_index"] == 1
    assert group["legs"][0]["exchange"] == "kalshi"
    assert group["legs"][1]["exchange"] == "polymarket"


def test_log_recommendation_group_ttl(db, session_id):
    _, expires_at = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        ttl_minutes=30,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    group = db.get_pending_groups()[0]
    created = datetime.fromisoformat(group["created_at"])
    expires = datetime.fromisoformat(expires_at)
    delta = (expires - created).total_seconds() / 60
    assert 29 <= delta <= 31


def test_get_pending_groups(db, session_id):
    db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    groups = db.get_pending_groups()
    assert len(groups) == 1
    assert groups[0]["status"] == "pending"
    assert "legs" in groups[0]


def test_get_group_not_found(db):
    assert db.get_group(9999) is None


def test_update_leg_status(db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    group = db.get_group(group_id)
    leg_id = group["legs"][0]["id"]
    db.update_leg_status(leg_id, "executed", order_id="ORD-123")
    updated = db.get_group(group_id)
    assert updated["legs"][0]["status"] == "executed"
    assert updated["legs"][0]["order_id"] == "ORD-123"
    assert updated["legs"][0]["executed_at"] is not None


def test_update_group_status_executed(db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    db.update_group_status(group_id, "executed")
    group = db.get_group(group_id)
    assert group["status"] == "executed"
    assert group["executed_at"] is not None


def test_update_group_status_rejected(db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    db.update_group_status(group_id, "rejected")
    group = db.get_group(group_id)
    assert group["status"] == "rejected"
    assert group["reviewed_at"] is not None


def test_get_recommendations_with_filter(db, session_id):
    db.log_recommendation_group(
        session_id=session_id,
        thesis="Test",
        estimated_edge_pct=5.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 45,
            }
        ],
    )
    recs = db.get_recommendations(status="pending")
    assert len(recs) == 1
    assert "legs" in recs[0]
    recs_empty = db.get_recommendations(status="executed")
    assert len(recs_empty) == 0


# ── Market snapshots ─────────────────────────────────────────────


def test_insert_market_snapshots_empty(db):
    assert db.insert_market_snapshots([]) == 0


def test_insert_market_snapshots_batch(db, sample_market_snapshot):
    rows = [sample_market_snapshot(ticker=f"T-{i}") for i in range(3)]
    count = db.insert_market_snapshots(rows)
    assert count == 3


def test_insert_market_snapshots_ignores_extra_keys(db, sample_market_snapshot):
    row = sample_market_snapshot(ticker="T-EXTRA")
    row["extra_key_not_in_schema"] = "should_be_ignored"
    count = db.insert_market_snapshots([row])
    assert count == 1


# ── Events upsert ────────────────────────────────────────────────


def test_upsert_event_insert(db, sample_event):
    ev = sample_event()
    db.upsert_event(**ev)
    row = get_row(db, Event, (ev["event_ticker"], ev["exchange"]))
    assert row is not None
    assert row["title"] == "Test Event"


def test_upsert_event_update(db, sample_event):
    ev = sample_event()
    db.upsert_event(**ev)
    ev["title"] = "Updated Title"
    db.upsert_event(**ev)
    row = get_row(db, Event, (ev["event_ticker"], ev["exchange"]))
    assert row is not None
    assert row["title"] == "Updated Title"


def test_upsert_event_composite_pk(db, sample_event):
    db.upsert_event(**sample_event(event_ticker="EVT-1", exchange="kalshi"))
    db.upsert_event(**sample_event(event_ticker="EVT-1", exchange="polymarket"))
    events = db.get_all_events()
    count = sum(1 for e in events if e["event_ticker"] == "EVT-1")
    assert count == 2


# ── get_session_state ────────────────────────────────────────────


def test_get_session_state_empty_db(db):
    state = db.get_session_state()
    expected_keys = {"last_session", "unreconciled_trades"}
    assert set(state.keys()) == expected_keys
    assert state["last_session"] is None
    assert state["unreconciled_trades"] == []


def test_get_session_state_populated(db, session_id):
    db.end_session(session_id, summary="s1")
    db.log_trade(session_id, "T-1", "buy", "yes", 10, status="placed")
    state = db.get_session_state()
    assert state["last_session"] is not None
    assert len(state["unreconciled_trades"]) == 1


# ── Backup ───────────────────────────────────────────────────────


def test_backup_creates_file(db, tmp_path):
    backup_dir = tmp_path / "backups"
    result = db.backup_if_needed(str(backup_dir))
    assert result is not None
    assert "agent_" in result


def test_backup_skips_recent(db, tmp_path):
    backup_dir = tmp_path / "backups"
    db.backup_if_needed(str(backup_dir))
    result = db.backup_if_needed(str(backup_dir))
    assert result is None


def test_backup_prunes_old(db, tmp_path):
    import time

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    first = db.backup_if_needed(str(backup_dir), max_age_hours=24)
    assert first is not None
    for _ in range(4):
        time.sleep(0.01)
        db.backup_if_needed(str(backup_dir), max_age_hours=0, max_backups=3)
    remaining = list(backup_dir.glob("agent_*.db"))
    assert len(remaining) <= 3
