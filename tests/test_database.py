"""Tests for finance_agent.database -- AgentDatabase (ORM-backed)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

# ── Schema / Init ────────────────────────────────────────────────


def test_db_creates_all_tables(db):
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    names = {r["name"] for r in rows}
    expected = {
        "market_snapshots",
        "events",
        "signals",
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
    rows = db.query("SELECT * FROM pragma_journal_mode")
    assert rows[0][next(iter(rows[0].keys()))] == "wal"


def test_db_foreign_keys_enabled(db):
    rows = db.query("SELECT * FROM pragma_foreign_keys")
    assert rows[0][next(iter(rows[0].keys()))] == 1


# ── query() ──────────────────────────────────────────────────────


def test_query_select_returns_dicts(db, session_id):
    rows = db.query("SELECT id, started_at FROM sessions WHERE id = ?", (session_id,))
    assert len(rows) == 1
    assert rows[0]["id"] == session_id
    assert rows[0]["started_at"] is not None


def test_query_with_cte(db, session_id):
    rows = db.query(
        "WITH s AS (SELECT id FROM sessions) SELECT id FROM s WHERE id = ?",
        (session_id,),
    )
    assert len(rows) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO sessions (id) VALUES ('x')",
        "DELETE FROM sessions WHERE id = 'x'",
        "UPDATE sessions SET summary = 'x'",
        "DROP TABLE sessions",
    ],
)
def test_query_rejects_writes(db, sql):
    with pytest.raises(ValueError, match="Only SELECT"):
        db.query(sql)


def test_query_empty_result(db):
    rows = db.query("SELECT id FROM sessions WHERE id = 'nonexistent'")
    assert rows == []


# ── Sessions ─────────────────────────────────────────────────────


def test_create_session_returns_8_char_id(db):
    sid = db.create_session()
    assert isinstance(sid, str)
    assert len(sid) == 8


def test_create_session_stores_started_at(db):
    sid = db.create_session()
    rows = db.query("SELECT started_at FROM sessions WHERE id = ?", (sid,))
    assert rows[0]["started_at"] is not None


def test_end_session_sets_fields(db, session_id):
    db.end_session(
        session_id,
        summary="Test summary",
        trades_placed=5,
        recommendations_made=3,
        pnl_usd=12.50,
    )
    rows = db.query(
        "SELECT ended_at, summary, trades_placed, recommendations_made, pnl_usd "
        "FROM sessions WHERE id = ?",
        (session_id,),
    )
    r = rows[0]
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
    rows = db.query("SELECT * FROM trades WHERE ticker = 'TICKER-X'")
    r = rows[0]
    assert r["exchange"] == "polymarket"
    assert r["price_cents"] == 45
    assert r["order_id"] == "ORD-1"
    assert r["status"] == "placed"


@pytest.mark.parametrize("exchange", ["kalshi", "polymarket"])
def test_log_trade_exchange(db, session_id, exchange):
    db.log_trade(session_id, "T-1", "buy", "yes", 1, exchange=exchange)
    rows = db.query(
        "SELECT exchange FROM trades WHERE ticker = 'T-1' AND exchange = ?", (exchange,)
    )
    assert rows[0]["exchange"] == exchange


def test_get_trades_with_filter(db, session_id):
    db.log_trade(session_id, "T-1", "buy", "yes", 10, exchange="kalshi")
    db.log_trade(session_id, "T-2", "sell", "no", 5, exchange="polymarket")
    trades = db.get_trades(exchange="kalshi")
    assert len(trades) == 1
    assert trades[0]["ticker"] == "T-1"


def test_update_trade_status(db, session_id):
    tid = db.log_trade(session_id, "T-1", "buy", "yes", 10, status="placed")
    db.update_trade_status(tid, "filled", result_json='{"filled": true}')
    rows = db.query("SELECT status, result_json FROM trades WHERE id = ?", (tid,))
    assert rows[0]["status"] == "filled"
    assert json.loads(rows[0]["result_json"])["filled"] is True


def test_update_trade_status_preserves_result_json(db, session_id):
    tid = db.log_trade(
        session_id, "T-1", "buy", "yes", 10, status="placed", result_json='{"orig": true}'
    )
    db.update_trade_status(tid, "filled")  # no result_json
    rows = db.query("SELECT result_json FROM trades WHERE id = ?", (tid,))
    assert json.loads(rows[0]["result_json"])["orig"] is True


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
    rows = db.query(
        "SELECT title FROM events WHERE event_ticker = ? AND exchange = ?",
        (ev["event_ticker"], ev["exchange"]),
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Test Event"


def test_upsert_event_update(db, sample_event):
    ev = sample_event()
    db.upsert_event(**ev)
    ev["title"] = "Updated Title"
    db.upsert_event(**ev)
    rows = db.query(
        "SELECT title FROM events WHERE event_ticker = ? AND exchange = ?",
        (ev["event_ticker"], ev["exchange"]),
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Updated Title"


def test_upsert_event_composite_pk(db, sample_event):
    db.upsert_event(**sample_event(event_ticker="EVT-1", exchange="kalshi"))
    db.upsert_event(**sample_event(event_ticker="EVT-1", exchange="polymarket"))
    rows = db.query("SELECT COUNT(*) as cnt FROM events WHERE event_ticker = 'EVT-1'")
    assert rows[0]["cnt"] == 2


# ── Signals ──────────────────────────────────────────────────────


def test_insert_signals_empty(db):
    assert db.insert_signals([]) == 0


def test_insert_signals_dict_details(db, sample_signal):
    sig = sample_signal(details_json={"spread": 10, "title": "Test"})
    count = db.insert_signals([sig])
    assert count == 1
    rows = db.query("SELECT details_json FROM signals WHERE ticker = ?", (sig["ticker"],))
    parsed = json.loads(rows[0]["details_json"])
    assert parsed["spread"] == 10


def test_insert_signals_string_details(db):
    sig = {
        "scan_type": "wide_spread",
        "ticker": "T-1",
        "signal_strength": 0.5,
        "estimated_edge_pct": 5.0,
        "details_json": '{"already": "serialized"}',
    }
    db.insert_signals([sig])
    rows = db.query("SELECT details_json FROM signals WHERE ticker = 'T-1'")
    assert json.loads(rows[0]["details_json"])["already"] == "serialized"


def test_expire_old_signals(db, sample_signal):
    db.insert_signals([sample_signal()])
    # Backdate via raw SQL through the query escape hatch won't work (SELECT only).
    # Instead, insert a signal with an old generated_at by manipulating the data.
    old_time = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
    with db._session_factory() as session:
        from finance_agent.models import Signal

        sig = session.query(Signal).filter(Signal.ticker == "TICKER-A").first()
        sig.generated_at = old_time
        session.commit()
    count = db.expire_old_signals(max_age_hours=48)
    assert count == 1
    rows = db.query("SELECT status FROM signals WHERE ticker = 'TICKER-A'")
    assert rows[0]["status"] == "expired"


def test_get_signals_with_filter(db, sample_signal):
    db.insert_signals([sample_signal(scan_type="arbitrage")])
    db.insert_signals([sample_signal(scan_type="cross_platform_candidate", ticker="T-2")])
    signals = db.get_signals(scan_type="arbitrage")
    assert len(signals) == 1
    assert signals[0]["scan_type"] == "arbitrage"


# ── get_session_state ────────────────────────────────────────────


def test_get_session_state_empty_db(db):
    state = db.get_session_state()
    expected_keys = {"last_session", "pending_signals", "unreconciled_trades"}
    assert set(state.keys()) == expected_keys
    assert state["last_session"] is None
    assert state["pending_signals"] == []
    assert state["unreconciled_trades"] == []


def test_get_session_state_populated(db, session_id, sample_signal):
    db.end_session(session_id, summary="s1")
    db.insert_signals([sample_signal()])
    db.log_trade(session_id, "T-1", "buy", "yes", 10, status="placed")
    state = db.get_session_state()
    assert state["last_session"] is not None
    assert len(state["pending_signals"]) == 1
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
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    first = db.backup_if_needed(str(backup_dir), max_age_hours=24)
    assert first is not None
    for _ in range(4):
        import time as _time

        _time.sleep(0.01)
        db.backup_if_needed(str(backup_dir), max_age_hours=0, max_backups=3)
    remaining = list(backup_dir.glob("agent_*.db"))
    assert len(remaining) <= 3
