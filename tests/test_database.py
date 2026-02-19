"""Tests for finance_agent.database -- AgentDatabase (ORM-backed, DuckDB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from helpers import get_row, raw_select

from finance_agent.models import Event, Session

# ── Schema / Init ────────────────────────────────────────────────


def test_db_creates_all_tables(db):
    rows = raw_select(
        db,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name",
    )
    names = {r["table_name"] for r in rows}
    expected = {
        "market_snapshots",
        "events",
        "trades",
        "sessions",
        "recommendation_groups",
        "recommendation_legs",
        "alembic_version",
    }
    assert expected.issubset(names)


def test_db_creates_views(db):
    rows = raw_select(
        db,
        "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW' AND table_schema = 'main'",
    )
    names = {r["table_name"] for r in rows}
    assert {"v_latest_markets", "v_daily_with_meta", "v_active_recommendations"}.issubset(names)


# ── Sessions ─────────────────────────────────────────────────────


def test_create_session_returns_8_char_id(db):
    sid = db.create_session()
    assert isinstance(sid, str)
    assert len(sid) == 8


def test_create_session_stores_started_at(db):
    sid = db.create_session()
    row = get_row(db, Session, sid)
    assert row["started_at"] is not None


def test_get_sessions(db):
    db.create_session()
    db.create_session()
    sessions = db.get_sessions()
    assert len(sessions) == 2


def test_get_sessions_derived_counts(db, session_id):
    """get_sessions returns rec and trade counts derived from related tables."""
    db.log_trade(session_id, "T-1", "buy", "yes", 10, status="placed")
    sessions = db.get_sessions()
    sess = next(s for s in sessions if s["id"] == session_id)
    assert sess["trades_placed"] == 1
    assert sess["recommendations_made"] == 0


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
        exchange="kalshi",
    )
    trades = db.get_trades()
    r = next(t for t in trades if t["ticker"] == "TICKER-X")
    assert r["exchange"] == "kalshi"
    assert r["price_cents"] == 45
    assert r["order_id"] == "ORD-1"
    assert r["status"] == "placed"


def test_log_trade_exchange(db, session_id):
    db.log_trade(session_id, "T-1", "buy", "yes", 1, exchange="kalshi")
    trades = db.get_trades(exchange="kalshi")
    assert trades[0]["exchange"] == "kalshi"


def test_get_trades_with_filter(db, session_id):
    db.log_trade(session_id, "T-1", "buy", "yes", 10, exchange="kalshi")
    db.log_trade(session_id, "T-2", "sell", "no", 5, exchange="kalshi")
    trades = db.get_trades(exchange="kalshi")
    assert len(trades) == 2


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
        thesis="Bracket arb opportunity",
        estimated_edge_pct=7.0,
        equivalence_notes="Same event, mutually exclusive outcomes",
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "market_title": "Leg 1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "market_title": "Leg 2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-3",
                "market_title": "Leg 3",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
        ],
    )
    group = db.get_group(group_id)
    assert group is not None
    assert len(group["legs"]) == 3
    assert group["legs"][0]["leg_index"] == 0
    assert group["legs"][1]["leg_index"] == 1
    assert group["legs"][2]["leg_index"] == 2
    assert all(leg["exchange"] == "kalshi" for leg in group["legs"])


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


# ── Settlement tracking ──────────────────────────────────────────


def test_get_unresolved_leg_tickers_empty(db):
    assert db.get_unresolved_leg_tickers() == []


def test_get_unresolved_leg_tickers(db, session_id):
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
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 50,
            },
        ],
    )
    tickers = db.get_unresolved_leg_tickers()
    assert set(tickers) == {"K-1", "K-2"}


def test_get_unresolved_deduplicates(db, session_id):
    """Same ticker in multiple groups returns only once."""
    for _ in range(2):
        db.log_recommendation_group(
            session_id=session_id,
            thesis="Test",
            estimated_edge_pct=5.0,
            legs=[
                {
                    "exchange": "kalshi",
                    "market_id": "K-SAME",
                    "action": "buy",
                    "side": "yes",
                    "quantity": 10,
                    "price_cents": 45,
                },
            ],
        )
    tickers = db.get_unresolved_leg_tickers()
    assert tickers.count("K-SAME") == 1


def test_settle_legs(db, session_id):
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
            },
        ],
    )
    count = db.settle_legs("K-1", 100)
    assert count == 1
    group = db.get_group(group_id)
    assert group["legs"][0]["settlement_value"] == 100
    assert group["legs"][0]["settled_at"] is not None


def test_settle_legs_idempotent(db, session_id):
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
            },
        ],
    )
    assert db.settle_legs("K-1", 100) == 1
    assert db.settle_legs("K-1", 100) == 0  # Already settled


def test_get_groups_pending_pnl_not_ready(db, session_id):
    """Group with unsettled legs should not appear."""
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
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 50,
            },
        ],
    )
    db.settle_legs("K-1", 100)  # Only one leg settled
    assert len(db.get_groups_pending_pnl()) == 0


def test_get_groups_pending_pnl_ready(db, session_id):
    """Group with all legs settled and no P&L computed should appear."""
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
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 50,
            },
        ],
    )
    db.settle_legs("K-1", 100)
    db.settle_legs("K-2", 0)
    groups = db.get_groups_pending_pnl()
    assert len(groups) == 1


def test_update_group_pnl(db, session_id):
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
            },
        ],
    )
    db.update_group_pnl(group_id, 1.5)
    group = db.get_group(group_id)
    assert group["hypothetical_pnl_usd"] == 1.5


def test_get_performance_summary_empty(db):
    perf = db.get_performance_summary()
    assert perf["total_pnl_usd"] == 0
    assert perf["total_settled"] == 0
    assert perf["wins"] == 0
    assert perf["losses"] == 0
    assert perf["settled_groups"] == []
    assert perf["pending_groups"] == []


def test_get_performance_summary_with_data(db, session_id):
    group_id, _ = db.log_recommendation_group(
        session_id=session_id,
        thesis="Test bracket",
        estimated_edge_pct=8.0,
        total_exposure_usd=50.0,
        legs=[
            {
                "exchange": "kalshi",
                "market_id": "K-1",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
            {
                "exchange": "kalshi",
                "market_id": "K-2",
                "action": "buy",
                "side": "yes",
                "quantity": 10,
                "price_cents": 30,
            },
        ],
    )
    db.settle_legs("K-1", 100)
    db.settle_legs("K-2", 0)
    db.update_group_pnl(group_id, 0.85)
    perf = db.get_performance_summary()
    assert perf["total_settled"] == 1
    assert perf["wins"] == 1
    assert perf["total_pnl_usd"] == 0.85
    assert len(perf["settled_groups"]) == 1
    assert len(perf["pending_groups"]) == 0


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
    events = db.get_all_events()
    count = sum(1 for e in events if e["event_ticker"] == "EVT-1")
    assert count == 1


# ── Kalshi daily upsert ──────────────────────────────────────────


def test_insert_kalshi_daily_upsert(db):
    """insert_kalshi_daily upserts on (date, ticker_name) conflict."""
    row = {
        "date": "2026-01-01",
        "ticker_name": "KX-FOO",
        "report_ticker": "KX-FOO-RPT",
        "payout_type": "binary",
        "open_interest": 100,
        "daily_volume": 50,
        "block_volume": 0,
        "high": 60,
        "low": 40,
        "status": "open",
    }
    assert db.insert_kalshi_daily([row]) == 1
    # Upsert same date+ticker with different OI
    row2 = {**row, "open_interest": 200}
    assert db.insert_kalshi_daily([row2]) == 1
    # Verify the upsert updated the value
    rows = raw_select(
        db,
        "SELECT open_interest FROM kalshi_daily WHERE ticker_name = :p0 AND date = :p1",
        ("KX-FOO", "2026-01-01"),
    )
    assert rows[0]["open_interest"] == 200


# ── get_session_state ────────────────────────────────────────────


def test_get_session_state_empty_db(db):
    state = db.get_session_state()
    expected_keys = {"last_session", "unreconciled_trades"}
    assert set(state.keys()) == expected_keys
    assert state["last_session"] is None
    assert state["unreconciled_trades"] == []


def test_get_session_state_excludes_current(db, session_id):
    """get_session_state with current_session_id excludes the current session."""
    second_id = db.create_session()
    state = db.get_session_state(current_session_id=second_id)
    assert state["last_session"] is not None
    assert state["last_session"]["id"] == session_id


def test_get_session_state_populated(db, session_id):
    current_id = db.create_session()
    db.log_trade(session_id, "T-1", "buy", "yes", 10, status="placed")
    state = db.get_session_state(current_session_id=current_id)
    assert state["last_session"] is not None
    assert state["last_session"]["id"] == session_id
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
    remaining = list(backup_dir.glob("agent_*.duckdb"))
    assert len(remaining) <= 3


# ── Trade → Leg linkage ─────────────────────────────────────────


def test_log_trade_with_leg_id(db, session_id):
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
    trade_id = db.log_trade(
        session_id,
        "K-1",
        "buy",
        "yes",
        10,
        price_cents=45,
        exchange="kalshi",
        leg_id=leg_id,
    )
    trades = db.get_trades()
    trade = next(t for t in trades if t["id"] == trade_id)
    assert trade["leg_id"] == leg_id


def test_log_trade_without_leg_id(db, session_id):
    trade_id = db.log_trade(session_id, "K-1", "buy", "yes", 10)
    trades = db.get_trades()
    trade = next(t for t in trades if t["id"] == trade_id)
    assert trade["leg_id"] is None


# ── Recommendation group (no FK constraint in DuckDB) ──────────


def test_recommendation_group_without_session(db):
    """Groups can be created without FK enforcement (DuckDB limitation)."""
    group_id, _ = db.log_recommendation_group(
        session_id="nonexistent",
        thesis="No FK constraint",
        estimated_edge_pct=1.0,
        legs=[{"exchange": "kalshi", "market_id": "K-1"}],
    )
    assert isinstance(group_id, int)


# ── Snapshot purge ──────────────────────────────────────────────


def test_purge_old_snapshots(db, sample_market_snapshot):
    old_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    recent_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    db.insert_market_snapshots(
        [
            sample_market_snapshot(ticker="OLD-1", captured_at=old_ts),
            sample_market_snapshot(ticker="OLD-2", captured_at=old_ts),
            sample_market_snapshot(ticker="NEW-1", captured_at=recent_ts),
        ]
    )
    deleted = db.purge_old_snapshots(retention_days=7)
    assert deleted == 2
    remaining = db.get_latest_snapshots(status="open")
    assert len(remaining) == 1
    assert remaining[0]["ticker"] == "NEW-1"


def test_purge_old_snapshots_nothing_to_purge(db, sample_market_snapshot):
    recent_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    db.insert_market_snapshots(
        [
            sample_market_snapshot(ticker="NEW-1", captured_at=recent_ts),
        ]
    )
    deleted = db.purge_old_snapshots(retention_days=7)
    assert deleted == 0


# ── v_latest_markets view ───────────────────────────────────────


def test_v_latest_markets_returns_latest_per_ticker(db, sample_market_snapshot):
    """View returns only the latest snapshot per ticker."""
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    new_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    db.insert_market_snapshots(
        [
            sample_market_snapshot(ticker="T-1", captured_at=old_ts, yes_bid=30, yes_ask=40),
            sample_market_snapshot(ticker="T-1", captured_at=new_ts, yes_bid=45, yes_ask=55),
        ]
    )
    rows = raw_select(db, "SELECT ticker, yes_bid FROM v_latest_markets WHERE ticker = 'T-1'")
    assert len(rows) == 1
    assert rows[0]["yes_bid"] == 45


# ── Bulk upsert (CSV staging) ───────────────────────────────────


def test_insert_kalshi_daily_bulk_skips_duplicates(db):
    """insert_kalshi_daily_bulk uses DO NOTHING — skips existing rows."""
    row = {
        "date": "2026-01-15",
        "ticker_name": "KX-BULK",
        "report_ticker": "KX-BULK-RPT",
        "payout_type": "binary",
        "open_interest": 100,
        "daily_volume": 50,
        "block_volume": 0,
        "high": 60,
        "low": 40,
        "status": "open",
    }
    assert db.insert_kalshi_daily_bulk([row]) == 1
    # Insert same row again — should be skipped (DO NOTHING)
    assert db.insert_kalshi_daily_bulk([row]) == 1  # returns len(rows), not inserted count
    rows = raw_select(
        db,
        "SELECT open_interest FROM kalshi_daily WHERE ticker_name = 'KX-BULK'",
    )
    assert len(rows) == 1
    assert rows[0]["open_interest"] == 100  # original value preserved


def test_insert_kalshi_daily_bulk_in_batch_duplicates(db):
    """In-batch duplicates are handled via DISTINCT ON."""
    rows = [
        {
            "date": "2026-02-01",
            "ticker_name": "KX-DUP",
            "report_ticker": "R1",
            "payout_type": "binary",
            "open_interest": 100,
            "daily_volume": 50,
            "block_volume": 0,
            "high": 60,
            "low": 40,
            "status": "open",
        },
        {
            "date": "2026-02-01",
            "ticker_name": "KX-DUP",
            "report_ticker": "R2",
            "payout_type": "binary",
            "open_interest": 200,
            "daily_volume": 100,
            "block_volume": 0,
            "high": 70,
            "low": 30,
            "status": "open",
        },
    ]
    assert db.insert_kalshi_daily_bulk(rows) == 2
    result = raw_select(
        db,
        "SELECT COUNT(*) as cnt FROM kalshi_daily WHERE ticker_name = 'KX-DUP'",
    )
    assert result[0]["cnt"] == 1  # only 1 row, not 2


def test_insert_kalshi_daily_bulk_null_values(db):
    """NULL values in nullable INTEGER columns are preserved through CSV staging."""
    row = {
        "date": "2026-03-01",
        "ticker_name": "KX-NULL",
        "report_ticker": "KX-NULL-RPT",
        "payout_type": "binary",
        "open_interest": None,
        "daily_volume": None,
        "block_volume": None,
        "high": None,
        "low": None,
        "status": "open",
    }
    db.insert_kalshi_daily_bulk([row])
    rows = raw_select(
        db,
        "SELECT high, low, daily_volume FROM kalshi_daily WHERE ticker_name = 'KX-NULL'",
    )
    assert len(rows) == 1
    assert rows[0]["high"] is None
    assert rows[0]["low"] is None
    assert rows[0]["daily_volume"] is None


def test_upsert_market_meta_does_not_mutate_input(db):
    """upsert_market_meta should not mutate the caller's dicts."""
    original = {"ticker": "KX-MUT", "title": "Mutation Test"}
    input_rows = [original.copy()]
    db.upsert_market_meta(input_rows)
    # Original dict should NOT have first_seen/last_seen added
    assert "first_seen" not in original


def test_upsert_market_meta_preserves_first_seen(db):
    """ON CONFLICT preserves first_seen but updates last_seen."""
    db.upsert_market_meta([{"ticker": "KX-FS", "title": "First"}])
    rows = raw_select(
        db, "SELECT first_seen, last_seen FROM kalshi_market_meta WHERE ticker = 'KX-FS'"
    )
    first_seen_1 = rows[0]["first_seen"]

    db.upsert_market_meta([{"ticker": "KX-FS", "title": "Second"}])
    rows = raw_select(
        db, "SELECT first_seen, last_seen, title FROM kalshi_market_meta WHERE ticker = 'KX-FS'"
    )
    assert rows[0]["first_seen"] == first_seen_1  # preserved
    assert rows[0]["title"] == "Second"  # updated


def test_bulk_upsert_empty_rows(db):
    """Empty list returns 0 immediately."""
    assert db.insert_kalshi_daily([]) == 0
    assert db.insert_kalshi_daily_bulk([]) == 0
    assert db.upsert_market_meta([]) == 0
