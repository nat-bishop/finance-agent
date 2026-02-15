"""Tests for finance_agent.database -- AgentDatabase."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from finance_agent.database import _now

# ── Schema / Init ────────────────────────────────────────────────


def test_db_creates_all_tables(db):
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    names = {r["name"] for r in rows}
    expected = {
        "market_snapshots",
        "events",
        "signals",
        "trades",
        "predictions",
        "portfolio_snapshots",
        "sessions",
        "watchlist",
        "recommendations",
        "alembic_version",
    }
    assert expected.issubset(names)


def test_db_wal_mode(db):
    rows = db.query("SELECT * FROM pragma_journal_mode")
    # pragma_journal_mode returns a single row with a single column
    assert rows[0][next(iter(rows[0].keys()))] == "wal"


def test_db_foreign_keys_enabled(db):
    rows = db.query("SELECT * FROM pragma_foreign_keys")
    assert rows[0][next(iter(rows[0].keys()))] == 1


# ── query() ──────────────────────────────────────────────────────


def test_query_select_returns_dicts(db, session_id):
    rows = db.query("SELECT id, profile FROM sessions WHERE id = ?", (session_id,))
    assert len(rows) == 1
    assert rows[0]["id"] == session_id
    assert rows[0]["profile"] == "test"


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
        "UPDATE sessions SET profile = 'x'",
        "DROP TABLE sessions",
    ],
)
def test_query_rejects_writes(db, sql):
    with pytest.raises(ValueError, match="Only SELECT"):
        db.query(sql)


def test_query_empty_result(db):
    rows = db.query("SELECT id FROM sessions WHERE id = 'nonexistent'")
    assert rows == []


# ── execute / executemany ────────────────────────────────────────


def test_execute_returns_cursor(db):
    cursor = db.execute(
        "INSERT INTO sessions (id, started_at, profile) VALUES (?, ?, ?)",
        ("test-ex", _now(), "demo"),
    )
    assert cursor.lastrowid is not None


def test_executemany_inserts(db, sample_market_snapshot):
    rows = [sample_market_snapshot(ticker=f"T-{i}") for i in range(3)]
    cols = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    params_list = [tuple(r[c] for c in cols) for r in rows]
    db.executemany(
        f"INSERT INTO market_snapshots ({', '.join(cols)}) VALUES ({placeholders})",
        params_list,
    )
    result = db.query("SELECT COUNT(*) as cnt FROM market_snapshots")
    assert result[0]["cnt"] == 3


# ── Sessions ─────────────────────────────────────────────────────


def test_create_session_returns_8_char_id(db):
    sid = db.create_session("demo")
    assert isinstance(sid, str)
    assert len(sid) == 8


def test_create_session_stores_profile(db):
    sid = db.create_session("prod")
    rows = db.query("SELECT profile, started_at FROM sessions WHERE id = ?", (sid,))
    assert rows[0]["profile"] == "prod"
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
    rows = db.query("SELECT exchange FROM trades WHERE ticker = 'T-1'")
    assert rows[0]["exchange"] == exchange


# ── Predictions ──────────────────────────────────────────────────


def test_log_prediction_returns_id(db):
    pid = db.log_prediction("MKT-1", 0.65)
    assert isinstance(pid, int)
    assert pid > 0


def test_resolve_prediction_sets_outcome(db):
    pid = db.log_prediction("MKT-1", 0.75)
    db.resolve_prediction(pid, 1)
    rows = db.query("SELECT outcome, resolved_at FROM predictions WHERE id = ?", (pid,))
    assert rows[0]["outcome"] == 1
    assert rows[0]["resolved_at"] is not None


def test_log_prediction_with_extras(db):
    pid = db.log_prediction(
        "MKT-1", 0.70, market_price_cents=65, methodology="orderbook", notes="test"
    )
    rows = db.query("SELECT methodology, notes FROM predictions WHERE id = ?", (pid,))
    assert rows[0]["methodology"] == "orderbook"
    assert rows[0]["notes"] == "test"


# ── auto_resolve_predictions ─────────────────────────────────────


def test_auto_resolve_no_unresolved(db):
    result = db.auto_resolve_predictions()
    assert result == []


def test_auto_resolve_matches_settled(db, sample_market_snapshot):
    pid = db.log_prediction("TICKER-A", 0.70)
    db.insert_market_snapshots(
        [
            sample_market_snapshot(
                ticker="TICKER-A",
                status="settled",
                settlement_value=1,
            )
        ]
    )
    resolved = db.auto_resolve_predictions()
    assert len(resolved) == 1
    assert resolved[0]["prediction_id"] == pid
    assert resolved[0]["outcome"] == 1


@pytest.mark.parametrize(
    "prediction,outcome,expected_correct",
    [
        (0.7, 1, True),
        (0.3, 1, False),
        (0.7, 0, False),
        (0.3, 0, True),
    ],
)
def test_auto_resolve_correctness(
    db, sample_market_snapshot, prediction, outcome, expected_correct
):
    db.log_prediction("TICKER-A", prediction)
    db.insert_market_snapshots(
        [sample_market_snapshot(ticker="TICKER-A", status="settled", settlement_value=outcome)]
    )
    resolved = db.auto_resolve_predictions()
    assert resolved[0]["correct"] is expected_correct


def test_auto_resolve_skips_unsettled(db, sample_market_snapshot):
    db.log_prediction("TICKER-A", 0.70)
    db.insert_market_snapshots([sample_market_snapshot(ticker="TICKER-A", status="open")])
    resolved = db.auto_resolve_predictions()
    assert resolved == []


# ── _compute_calibration ─────────────────────────────────────────


def test_compute_calibration_no_data(db):
    assert db._compute_calibration() is None


def test_compute_calibration_perfect(db):
    # 10 predictions: all 1.0 with outcome 1, all 0.0 with outcome 0
    for _ in range(5):
        pid = db.log_prediction("M-A", 1.0)
        db.resolve_prediction(pid, 1)
    for _ in range(5):
        pid = db.log_prediction("M-B", 0.0)
        db.resolve_prediction(pid, 0)
    cal = db._compute_calibration()
    assert cal is not None
    assert cal["brier_score"] == 0.0
    assert cal["correct"] == 10
    assert cal["total"] == 10


def test_compute_calibration_brier_math(db):
    # 4 predictions with known Brier: (0.7-1)^2 + (0.3-0)^2 + (0.6-1)^2 + (0.4-0)^2
    # = 0.09 + 0.09 + 0.16 + 0.16 = 0.50 / 4 = 0.125
    data = [(0.7, 1), (0.3, 0), (0.6, 1), (0.4, 0)]
    for pred, outcome in data:
        pid = db.log_prediction("M-X", pred)
        db.resolve_prediction(pid, outcome)
    cal = db._compute_calibration()
    assert cal is not None
    assert cal["brier_score"] == 0.125


def test_compute_calibration_has_buckets(db):
    # predictions in different ranges
    data = [(0.1, 0), (0.3, 0), (0.5, 1), (0.7, 1), (0.9, 1)]
    for pred, outcome in data:
        pid = db.log_prediction("M-X", pred)
        db.resolve_prediction(pid, outcome)
    cal = db._compute_calibration()
    assert cal is not None
    assert len(cal["buckets"]) > 0
    for bucket in cal["buckets"]:
        assert "range" in bucket
        assert "count" in bucket
        assert "accuracy" in bucket


# ── Market snapshots ─────────────────────────────────────────────


def test_insert_market_snapshots_empty(db):
    assert db.insert_market_snapshots([]) == 0


def test_insert_market_snapshots_batch(db, sample_market_snapshot):
    rows = [sample_market_snapshot(ticker=f"T-{i}") for i in range(3)]
    count = db.insert_market_snapshots(rows)
    assert count == 3


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
    # Insert a signal, then manually backdate its generated_at
    db.insert_signals([sample_signal()])
    old_time = (datetime.now(UTC) - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "UPDATE signals SET generated_at = ? WHERE ticker = 'TICKER-A'",
        (old_time,),
    )
    count = db.expire_old_signals(max_age_hours=48)
    assert count == 1
    rows = db.query("SELECT status FROM signals WHERE ticker = 'TICKER-A'")
    assert rows[0]["status"] == "expired"


# ── Recommendations ──────────────────────────────────────────────


def test_log_recommendation_returns_id(db, session_id):
    rec_id = db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-MKT-1",
        market_title="Test Market",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
    )
    assert isinstance(rec_id, int)
    assert rec_id > 0


def test_log_recommendation_sets_expires_at(db, session_id):
    rec_id = db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-MKT-1",
        market_title="Test",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
        ttl_minutes=30,
    )
    rec = db.get_recommendation(rec_id)
    assert rec is not None
    assert rec["expires_at"] is not None
    # expires_at should be ~30 minutes after created_at
    created = datetime.fromisoformat(rec["created_at"])
    expires = datetime.fromisoformat(rec["expires_at"])
    delta = (expires - created).total_seconds() / 60
    assert 29 <= delta <= 31


def test_get_pending_recommendations(db, session_id):
    db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-1",
        market_title="Leg 1",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
        group_id="G-1",
        leg_index=0,
    )
    db.log_recommendation(
        session_id=session_id,
        exchange="polymarket",
        market_id="P-1",
        market_title="Leg 2",
        action="sell",
        side="yes",
        quantity=10,
        price_cents=52,
        group_id="G-1",
        leg_index=1,
    )
    recs = db.get_pending_recommendations()
    assert len(recs) == 2
    assert recs[0]["leg_index"] == 0
    assert recs[1]["leg_index"] == 1
    assert recs[0]["group_id"] == recs[1]["group_id"] == "G-1"


def test_update_recommendation_status_executed(db, session_id):
    rec_id = db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-1",
        market_title="Test",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
    )
    db.update_recommendation_status(rec_id, "executed", order_id="ORD-123")
    rec = db.get_recommendation(rec_id)
    assert rec["status"] == "executed"
    assert rec["executed_at"] is not None
    assert rec["order_id"] == "ORD-123"


def test_update_recommendation_status_rejected(db, session_id):
    rec_id = db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-1",
        market_title="Test",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
    )
    db.update_recommendation_status(rec_id, "rejected")
    rec = db.get_recommendation(rec_id)
    assert rec["status"] == "rejected"
    assert rec["reviewed_at"] is not None


def test_get_recommendation_not_found(db):
    assert db.get_recommendation(9999) is None


# ── get_session_state ────────────────────────────────────────────


def test_get_session_state_empty_db(db):
    state = db.get_session_state()
    expected_keys = {
        "last_session",
        "pending_signals",
        "unresolved_predictions",
        "calibration",
        "signal_history",
        "portfolio_delta",
        "recent_trades",
        "unreconciled_trades",
        "pending_recommendations",
        "recent_recommendations",
    }
    assert set(state.keys()) == expected_keys
    assert state["last_session"] is None
    assert state["pending_signals"] == []
    assert state["calibration"] is None


def test_get_session_state_populated(db, session_id, sample_market_snapshot, sample_signal):
    # End a session so last_session is populated
    db.end_session(session_id, summary="s1")

    # Add signals
    db.insert_signals([sample_signal()])

    # Add a prediction
    db.log_prediction("T-1", 0.65)

    # Add a trade
    db.log_trade(session_id, "T-1", "buy", "yes", 10, status="placed")

    # Add a recommendation
    db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-1",
        market_title="Test",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
    )

    # Add portfolio
    db.log_portfolio_snapshot(session_id, 100.0)

    state = db.get_session_state()
    assert state["last_session"] is not None
    assert len(state["pending_signals"]) == 1
    assert len(state["unresolved_predictions"]) == 1
    assert len(state["recent_trades"]) == 1
    assert len(state["unreconciled_trades"]) == 1
    assert len(state["pending_recommendations"]) == 1
    assert len(state["recent_recommendations"]) == 1
    assert state["signal_history"] != []
    assert state["portfolio_delta"] is not None


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
    # Create initial backup, then make it old by setting max_age_hours very low
    first = db.backup_if_needed(str(backup_dir), max_age_hours=24)
    assert first is not None
    # Repeatedly force backups by using max_age_hours=0
    for _ in range(4):
        import time as _time

        _time.sleep(0.01)  # ensure different timestamps
        db.backup_if_needed(str(backup_dir), max_age_hours=0, max_backups=3)
    remaining = list(backup_dir.glob("agent_*.db"))
    assert len(remaining) <= 3


# ── TUI query methods ────────────────────────────────────────────


def test_get_recommendations_with_filter(db, session_id):
    db.log_recommendation(
        session_id=session_id,
        exchange="kalshi",
        market_id="K-1",
        market_title="Test",
        action="buy",
        side="yes",
        quantity=10,
        price_cents=45,
    )
    recs = db.get_recommendations(status="pending")
    assert len(recs) == 1
    recs_empty = db.get_recommendations(status="executed")
    assert len(recs_empty) == 0


def test_get_trades_with_filter(db, session_id):
    db.log_trade(session_id, "T-1", "buy", "yes", 10, exchange="kalshi")
    db.log_trade(session_id, "T-2", "sell", "no", 5, exchange="polymarket")
    trades = db.get_trades(exchange="kalshi")
    assert len(trades) == 1
    assert trades[0]["ticker"] == "T-1"


def test_get_sessions(db):
    db.create_session("a")
    db.create_session("b")
    sessions = db.get_sessions()
    assert len(sessions) == 2
