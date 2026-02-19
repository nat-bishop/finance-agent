"""SQLite database for agent state, market data, and trades.

Uses SQLAlchemy ORM with Alembic autogenerate migrations.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, event, func, insert, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from finance_agent.constants import (
    EXCHANGE_KALSHI,
    STATUS_EXECUTED,
    STATUS_OPEN,
    STATUS_PENDING,
    STATUS_PLACED,
    STRATEGY_BRACKET,
)
from finance_agent.models import (
    Event,
    KalshiDaily,
    KalshiMarketMeta,
    MarketSnapshot,
    RecommendationGroup,
    RecommendationLeg,
    Session,
    Trade,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AgentDatabase:
    """SQLite database for the trading agent.

    Uses WAL mode for concurrent access (collector + agent).
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Opening database: %s", self.db_path)

        self._engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"timeout": 30, "check_same_thread": False},
            echo=False,
        )

        @event.listens_for(self._engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            # EXCLUSIVE locking stores WAL index in heap memory instead of
            # a shared-memory file, avoiding mmap — required for Docker
            # bind mounts on Windows/Mac where POSIX locking is unsupported.
            cursor.execute("PRAGMA locking_mode=EXCLUSIVE")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                logger.warning("WAL mode unavailable, falling back to DELETE journal")
                try:
                    cursor.execute("PRAGMA journal_mode=DELETE")
                except Exception:
                    logger.warning("Could not set journal mode, using database default")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            with suppress(Exception):
                cursor.execute("PRAGMA mmap_size=268435456")  # 256 MB mmap window
            cursor.execute("PRAGMA cache_size=-131072")  # 128 MB page cache
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()

        self._session_factory = sessionmaker(bind=self._engine)
        self._bulk_mode = False
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Run Alembic migrations to bring schema up to date."""
        from alembic import command
        from alembic.config import Config

        logger.debug("Running Alembic migrations...")
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")
        with self._engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        logger.debug("Migrations complete")

    def close(self) -> None:
        logger.debug("Closing database connection")
        self._engine.dispose()

    def maintenance(self, *, vacuum: bool = False) -> None:
        """Run database maintenance: update statistics, checkpoint WAL.

        Safe to call while other connections are open (uses PASSIVE checkpoint).
        Set ``vacuum=True`` only when no other connections are active and
        sufficient disk space is available (~1x DB size).
        """
        import time

        t0 = time.time()
        conn = self._engine.raw_connection()
        try:
            cursor = conn.cursor()
            # Bound ANALYZE work so first run finishes in seconds, not minutes
            cursor.execute("PRAGMA analysis_limit=1000")
            cursor.execute("PRAGMA optimize")
            # PASSIVE: checkpoint as much as possible without blocking readers
            cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
            row = cursor.fetchone()
            busy, log_pages, checkpointed = row or (0, 0, 0)
            cursor.close()
            conn.commit()
        finally:
            conn.close()

        elapsed = time.time() - t0
        logger.info(
            "Maintenance: optimize + checkpoint in %.1fs (wal_pages=%d, checkpointed=%d, busy=%d)",
            elapsed,
            log_pages,
            checkpointed,
            busy,
        )

        if vacuum:
            logger.info("Running VACUUM (this may take several minutes)...")
            t0 = time.time()
            conn = self._engine.raw_connection()
            try:
                conn.execute("VACUUM")
                conn.commit()
            finally:
                conn.close()
            logger.info("VACUUM completed in %.1fs", time.time() - t0)

    # ── Market snapshot queries ─────────────────────────────────

    def get_latest_snapshots(
        self,
        *,
        exchange: str | None = None,
        status: str = STATUS_OPEN,
        require_mid_price: bool = False,
    ) -> list[dict[str, Any]]:
        """Get the most recent snapshot per (exchange, ticker). Returns list of dicts."""
        with self._session_factory() as session:
            # Subquery: max captured_at per (exchange, ticker)
            latest_sel = (
                select(
                    MarketSnapshot.exchange,
                    MarketSnapshot.ticker,
                    func.max(MarketSnapshot.captured_at).label("max_ts"),
                )
                .where(MarketSnapshot.status == status)
                .group_by(MarketSnapshot.exchange, MarketSnapshot.ticker)
            )
            if exchange:
                latest_sel = latest_sel.where(MarketSnapshot.exchange == exchange)
            latest_sub = latest_sel.subquery()

            # Main query: join to get full row
            stmt = select(MarketSnapshot).join(
                latest_sub,
                (MarketSnapshot.exchange == latest_sub.c.exchange)
                & (MarketSnapshot.ticker == latest_sub.c.ticker)
                & (MarketSnapshot.captured_at == latest_sub.c.max_ts),
            )
            if require_mid_price:
                stmt = stmt.where(MarketSnapshot.mid_price_cents.isnot(None))
            stmt = stmt.order_by(
                MarketSnapshot.category,
                MarketSnapshot.exchange,
                MarketSnapshot.event_ticker,
                MarketSnapshot.title,
            )
            return [s.to_dict() for s in session.scalars(stmt).all()]

    # ── Event queries ────────────────────────────────────────

    def get_mutually_exclusive_events(self) -> list[dict[str, Any]]:
        """Get events with mutually_exclusive=1 and non-null markets_json."""
        with self._session_factory() as session:
            stmt = select(Event).where(
                Event.mutually_exclusive == 1,
                Event.markets_json.isnot(None),
            )
            return [e.to_dict() for e in session.scalars(stmt).all()]

    def get_all_events(self) -> list[dict[str, Any]]:
        """Get all events (for market listings grouping)."""
        with self._session_factory() as session:
            return [e.to_dict() for e in session.scalars(select(Event)).all()]

    # ── Sessions ──────────────────────────────────────────────

    def create_session(self) -> str:
        """Create a new session, return its ID."""
        session_id = str(uuid.uuid4())[:8]
        with self._session_factory() as session:
            session.add(Session(id=session_id, started_at=_now()))
            session.commit()
        return session_id

    # ── Trades (lean schema) ──────────────────────────────────

    def log_trade(
        self,
        session_id: str,
        ticker: str,
        action: str,
        side: str,
        quantity: int,
        price_cents: int | None = None,
        order_type: str | None = None,
        order_id: str | None = None,
        status: str | None = None,
        result_json: str | None = None,
        exchange: str = EXCHANGE_KALSHI,
        leg_id: int | None = None,
    ) -> int:
        trade = Trade(
            session_id=session_id,
            leg_id=leg_id,
            exchange=exchange,
            timestamp=_now(),
            ticker=ticker,
            action=action,
            side=side,
            quantity=quantity,
            price_cents=price_cents,
            order_type=order_type,
            order_id=order_id,
            status=status,
            result_json=result_json,
        )
        with self._session_factory() as session:
            session.add(trade)
            session.commit()
            return trade.id  # type: ignore[return-value]

    # ── Recommendation Groups ─────────────────────────────────

    def log_recommendation_group(
        self,
        session_id: str,
        thesis: str | None = None,
        estimated_edge_pct: float | None = None,
        equivalence_notes: str | None = None,
        legs: list[dict[str, Any]] | None = None,
        ttl_minutes: int = 60,
        total_exposure_usd: float | None = None,
        computed_edge_pct: float | None = None,
        computed_fees_usd: float | None = None,
        strategy: str = STRATEGY_BRACKET,
    ) -> tuple[int, str]:
        """Insert a recommendation group + legs atomically. Returns (group_id, expires_at)."""
        now = _now()
        expires_at = (datetime.fromisoformat(now) + timedelta(minutes=ttl_minutes)).isoformat()

        group = RecommendationGroup(
            session_id=session_id,
            created_at=now,
            thesis=thesis,
            equivalence_notes=equivalence_notes,
            estimated_edge_pct=estimated_edge_pct,
            expires_at=expires_at,
            total_exposure_usd=total_exposure_usd,
            computed_edge_pct=computed_edge_pct,
            computed_fees_usd=computed_fees_usd,
            strategy=strategy,
        )
        for i, leg in enumerate(legs or []):
            group.legs.append(
                RecommendationLeg(
                    leg_index=i,
                    exchange=leg["exchange"],
                    market_id=leg["market_id"],
                    market_title=leg.get("market_title"),
                    action=leg.get("action"),
                    side=leg.get("side"),
                    quantity=leg.get("quantity"),
                    price_cents=leg.get("price_cents"),
                    is_maker=leg.get("is_maker"),
                    orderbook_snapshot_json=leg.get("orderbook_snapshot_json"),
                )
            )

        with self._session_factory() as session:
            session.add(group)
            session.commit()
            group_id = group.id

        return group_id, expires_at  # type: ignore[return-value]

    def get_pending_groups(self) -> list[dict[str, Any]]:
        """Return pending groups with nested legs list."""
        with self._session_factory() as session:
            stmt = (
                select(RecommendationGroup)
                .where(RecommendationGroup.status == STATUS_PENDING)
                .order_by(RecommendationGroup.created_at.desc())
            )
            groups = session.scalars(stmt).all()
            return [g.to_dict() for g in groups]

    def get_group(self, group_id: int) -> dict[str, Any] | None:
        """Return a single group with legs."""
        with self._session_factory() as session:
            group = session.get(RecommendationGroup, group_id)
            if not group:
                return None
            return group.to_dict()

    def update_leg_status(self, leg_id: int, status: str, order_id: str | None = None) -> None:
        """Update a single leg's status after exchange API call."""
        with self._session_factory() as session:
            leg = session.get(RecommendationLeg, leg_id)
            if leg:
                leg.status = status
                leg.order_id = order_id
                leg.executed_at = _now() if status == STATUS_EXECUTED else None
                session.commit()

    def update_group_status(self, group_id: int, status: str) -> None:
        """Set group status. Also sets reviewed_at or executed_at timestamp."""
        with self._session_factory() as session:
            group = session.get(RecommendationGroup, group_id)
            if group:
                group.status = status
                ts_col = "executed_at" if status == STATUS_EXECUTED else "reviewed_at"
                setattr(group, ts_col, _now())
                session.commit()

    def update_leg_fill(self, leg_id: int, fill_price_cents: int, fill_quantity: int) -> None:
        """Record actual fill data from exchange after order executes."""
        with self._session_factory() as session:
            leg = session.get(RecommendationLeg, leg_id)
            if leg:
                leg.fill_price_cents = fill_price_cents
                leg.fill_quantity = fill_quantity
                session.commit()

    def update_group_computed_fields(
        self,
        group_id: int,
        computed_edge_pct: float | None = None,
        computed_fees_usd: float | None = None,
    ) -> None:
        """Update code-computed fields (e.g. at execution time with fresh orderbook)."""
        with self._session_factory() as session:
            group = session.get(RecommendationGroup, group_id)
            if group:
                if computed_edge_pct is not None:
                    group.computed_edge_pct = computed_edge_pct
                if computed_fees_usd is not None:
                    group.computed_fees_usd = computed_fees_usd
                session.commit()

    # ── Settlement tracking ────────────────────────────────────

    def get_unresolved_leg_tickers(self) -> list[str]:
        """Return distinct market tickers from recommendation legs not yet settled."""
        with self._session_factory() as session:
            stmt = (
                select(RecommendationLeg.market_id)
                .where(RecommendationLeg.settlement_value.is_(None))
                .distinct()
            )
            return list(session.scalars(stmt).all())

    def settle_legs(self, ticker: str, settlement_value: int) -> int:
        """Mark all unresolved legs for a ticker as settled. Returns count updated."""
        now = _now()
        with self._session_factory() as session:
            legs = session.scalars(
                select(RecommendationLeg).where(
                    RecommendationLeg.market_id == ticker,
                    RecommendationLeg.settlement_value.is_(None),
                )
            ).all()
            for leg in legs:
                leg.settlement_value = settlement_value
                leg.settled_at = now
            session.commit()
            return len(legs)

    def get_groups_pending_pnl(self) -> list[dict[str, Any]]:
        """Return groups where all legs are settled but P&L hasn't been computed."""
        with self._session_factory() as session:
            unsettled_groups = (
                select(RecommendationLeg.group_id)
                .where(RecommendationLeg.settlement_value.is_(None))
                .distinct()
                .subquery()
            )
            stmt = select(RecommendationGroup).where(
                RecommendationGroup.hypothetical_pnl_usd.is_(None),
                RecommendationGroup.id.notin_(select(unsettled_groups.c.group_id)),
            )
            groups = session.scalars(stmt).all()
            return [g.to_dict() for g in groups if g.legs]

    def update_group_pnl(self, group_id: int, pnl_usd: float) -> None:
        """Set the hypothetical P&L for a recommendation group."""
        with self._session_factory() as session:
            group = session.get(RecommendationGroup, group_id)
            if group:
                group.hypothetical_pnl_usd = pnl_usd
                session.commit()

    def get_performance_summary(self) -> dict[str, Any]:
        """Return aggregate and per-group performance data for the P&L screen."""
        with self._session_factory() as session:
            settled_groups = session.scalars(
                select(RecommendationGroup)
                .where(RecommendationGroup.hypothetical_pnl_usd.isnot(None))
                .order_by(RecommendationGroup.created_at.desc())
            ).all()

            pending_groups = session.scalars(
                select(RecommendationGroup)
                .where(RecommendationGroup.hypothetical_pnl_usd.is_(None))
                .order_by(RecommendationGroup.created_at.desc())
            ).all()
            pending_groups = [g for g in pending_groups if g.legs]

            total_pnl = sum(g.hypothetical_pnl_usd or 0.0 for g in settled_groups)
            wins = sum(1 for g in settled_groups if (g.hypothetical_pnl_usd or 0) > 0)
            losses = sum(1 for g in settled_groups if (g.hypothetical_pnl_usd or 0) <= 0)

            edge_diffs: list[float] = []
            for g in settled_groups:
                pnl = g.hypothetical_pnl_usd
                if (
                    pnl is not None
                    and g.estimated_edge_pct
                    and g.total_exposure_usd
                    and g.total_exposure_usd > 0
                ):
                    realized_pct = (pnl / g.total_exposure_usd) * 100
                    edge_diffs.append(abs(g.estimated_edge_pct - realized_pct))

            return {
                "total_pnl_usd": round(total_pnl, 2),
                "total_settled": len(settled_groups),
                "wins": wins,
                "losses": losses,
                "win_rate": (
                    round(wins / len(settled_groups) * 100, 1) if settled_groups else 0.0
                ),
                "avg_edge_error": (
                    round(sum(edge_diffs) / len(edge_diffs), 2) if edge_diffs else None
                ),
                "settled_groups": [g.to_dict() for g in settled_groups],
                "pending_groups": [g.to_dict() for g in pending_groups],
            }

    # ── Market snapshots (bulk insert for collector) ──────────

    _SNAPSHOT_COLS = {c.name for c in MarketSnapshot.__table__.columns} - {"id"}

    def insert_market_snapshots(self, rows: list[dict[str, Any]]) -> int:
        """Bulk insert market snapshots. Returns count inserted."""
        if not rows:
            return 0
        filtered = [{k: v for k, v in row.items() if k in self._SNAPSHOT_COLS} for row in rows]
        with self._session_factory() as session:
            session.execute(insert(MarketSnapshot), filtered)
            session.commit()
        return len(filtered)

    def purge_old_snapshots(self, retention_days: int = 7) -> int:
        """Delete market snapshots older than retention_days. Returns count deleted."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self._session_factory() as session:
            result = session.execute(
                delete(MarketSnapshot).where(MarketSnapshot.captured_at < cutoff)
            )
            session.commit()
            deleted: int = result.rowcount  # type: ignore[attr-defined]
        if deleted:
            logger.info("Purged %d snapshots older than %d days", deleted, retention_days)
        return deleted

    # ── Kalshi daily history ─────────────────────────────────

    _DAILY_COLS = {c.name for c in KalshiDaily.__table__.columns} - {"id"}

    def get_kalshi_daily_max_date(self) -> str | None:
        """Return the latest date in kalshi_daily, or None if empty."""
        with self._session_factory() as session:
            return session.scalar(select(func.max(KalshiDaily.date)))

    def purge_old_daily(self, retention_days: int = 365, min_ticker_days: int = 5) -> int:
        """Purge old kalshi_daily rows for short-lived tickers.

        Deletes rows for tickers that:
        - Have no data newer than ``retention_days`` ago, AND
        - Have fewer than ``min_ticker_days`` total days of data

        This targets expired micro-market strike tickers (avg 12 day lifespan)
        while preserving long-running markets with rich history.
        Returns total number of rows deleted.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).strftime("%Y-%m-%d")

        # Find short-lived tickers with no recent data
        stale_tickers = (
            select(KalshiDaily.ticker_name)
            .group_by(KalshiDaily.ticker_name)
            .having(
                func.max(KalshiDaily.date) < cutoff,
                func.count(KalshiDaily.id) < min_ticker_days,
            )
        )

        with self._session_factory() as session:
            result = session.execute(
                delete(KalshiDaily).where(KalshiDaily.ticker_name.in_(stale_tickers))
            )
            session.commit()
            deleted: int = result.rowcount  # type: ignore[attr-defined]

        if deleted:
            logger.info(
                "Purged %d daily rows (tickers with <%d days, no data since %s)",
                deleted,
                min_ticker_days,
                cutoff,
            )
        return deleted

    def purge_inactive_daily(self) -> int:
        """Delete kalshi_daily rows with zero volume AND zero open interest.

        These are micro-markets with no trading activity — typically 94%+ of
        recent daily records.  Returns total number of rows deleted.
        """
        with self._session_factory() as session:
            result = session.execute(
                delete(KalshiDaily).where(
                    (KalshiDaily.daily_volume == 0) | (KalshiDaily.daily_volume.is_(None)),
                    (KalshiDaily.open_interest == 0) | (KalshiDaily.open_interest.is_(None)),
                )
            )
            session.commit()
            deleted: int = result.rowcount  # type: ignore[attr-defined]

        if deleted:
            logger.info("Purged %d inactive daily rows (zero volume and OI)", deleted)
        return deleted

    def insert_kalshi_daily(self, rows: list[dict[str, Any]]) -> int:
        """Bulk upsert daily Kalshi data. Returns count inserted/updated."""
        if not rows:
            return 0
        filtered = [{k: v for k, v in row.items() if k in self._DAILY_COLS} for row in rows]
        stmt = sqlite_insert(KalshiDaily)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "ticker_name"],
            set_={
                "report_ticker": stmt.excluded.report_ticker,
                "payout_type": stmt.excluded.payout_type,
                "open_interest": stmt.excluded.open_interest,
                "daily_volume": stmt.excluded.daily_volume,
                "block_volume": stmt.excluded.block_volume,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "status": stmt.excluded.status,
            },
        )
        with self._session_factory() as session:
            session.execute(stmt, filtered)
            session.commit()
        return len(filtered)

    _BULK_CHUNK_SIZE = 50_000

    def insert_kalshi_daily_bulk(self, rows: list[dict[str, Any]]) -> int:
        """Bulk insert daily Kalshi data, skipping existing rows.

        Uses ``ON CONFLICT DO NOTHING`` — faster than upsert for immutable
        historical data.  Chunks inserts to keep WAL size bounded.

        When called inside ``bulk_import_mode()``, applies aggressive PRAGMAs
        directly on the session connection (synchronous=OFF, larger cache).
        """
        if not rows:
            return 0
        filtered = [{k: v for k, v in row.items() if k in self._DAILY_COLS} for row in rows]
        stmt = sqlite_insert(KalshiDaily).on_conflict_do_nothing(
            index_elements=["date", "ticker_name"],
        )
        total = 0
        with self._session_factory() as session:
            if self._bulk_mode:
                session.execute(text("PRAGMA synchronous=OFF"))
                session.execute(text("PRAGMA cache_size=-256000"))
            try:
                for i in range(0, len(filtered), self._BULK_CHUNK_SIZE):
                    chunk = filtered[i : i + self._BULK_CHUNK_SIZE]
                    session.execute(stmt, chunk)
                    session.commit()
                    total += len(chunk)
            finally:
                if self._bulk_mode:
                    session.execute(text("PRAGMA synchronous=FULL"))
                    session.execute(text("PRAGMA cache_size=-131072"))
        return total

    @contextmanager
    def bulk_import_mode(self) -> Generator[None]:
        """Temporarily enable aggressive PRAGMAs for bulk data import.

        Sets a flag checked by ``insert_kalshi_daily_bulk()`` to apply
        performance PRAGMAs (synchronous=OFF, larger cache) on the actual
        session connection doing the work.  Safe for data that can be
        re-fetched (e.g. S3 backfill).
        """
        self._bulk_mode = True
        logger.info("Bulk import mode enabled")
        try:
            yield
        finally:
            self._bulk_mode = False
            logger.info("Bulk import mode disabled")

    # ── Kalshi market metadata ───────────────────────────────

    def upsert_market_meta(self, rows: list[dict[str, Any]]) -> int:
        """Bulk upsert market metadata. Preserves first_seen on conflict."""
        if not rows:
            return 0
        now = _now()
        for row in rows:
            row.setdefault("first_seen", now)
            row.setdefault("last_seen", now)
        stmt = sqlite_insert(KalshiMarketMeta)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={
                "event_ticker": stmt.excluded.event_ticker,
                "series_ticker": stmt.excluded.series_ticker,
                "title": stmt.excluded.title,
                "category": stmt.excluded.category,
                "last_seen": stmt.excluded.last_seen,
                # first_seen intentionally NOT updated
            },
        )
        with self._session_factory() as session:
            session.execute(stmt, rows)
            session.commit()
        return len(rows)

    def get_missing_meta_tickers(self, limit: int = 200, recency_days: int = 90) -> list[str]:
        """Return tickers in kalshi_daily that have no kalshi_market_meta row.

        Prioritizes recently-seen tickers (more likely to still exist in API).
        Filters to tickers with daily data within the last ``recency_days``.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=recency_days)).strftime("%Y-%m-%d")
        meta_tickers = select(KalshiMarketMeta.ticker)
        with self._session_factory() as session:
            stmt = (
                select(KalshiDaily.ticker_name)
                .where(
                    KalshiDaily.ticker_name.notin_(meta_tickers),
                    KalshiDaily.date >= cutoff,
                )
                .group_by(KalshiDaily.ticker_name)
                .order_by(func.max(KalshiDaily.date).desc())
                .limit(limit)
            )
            return list(session.scalars(stmt).all())

    # ── Events (upsert for collector) ─────────────────────────

    def upsert_event(
        self,
        event_ticker: str,
        exchange: str = EXCHANGE_KALSHI,
        series_ticker: str | None = None,
        title: str | None = None,
        category: str | None = None,
        mutually_exclusive: bool | None = None,
        markets_json: str | None = None,
    ) -> None:
        values = {
            "event_ticker": event_ticker,
            "exchange": exchange,
            "series_ticker": series_ticker,
            "title": title,
            "category": category,
            "mutually_exclusive": 1 if mutually_exclusive else 0,
            "last_updated": _now(),
            "markets_json": markets_json,
        }
        stmt = sqlite_insert(Event).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["event_ticker", "exchange"],
            set_={
                "series_ticker": stmt.excluded.series_ticker,
                "title": stmt.excluded.title,
                "category": stmt.excluded.category,
                "mutually_exclusive": stmt.excluded.mutually_exclusive,
                "last_updated": stmt.excluded.last_updated,
                "markets_json": stmt.excluded.markets_json,
            },
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

    # ── Session state (for startup) ───────────────────────────

    def get_session_state(self, current_session_id: str | None = None) -> dict[str, Any]:
        with self._session_factory() as session:
            stmt = select(Session).order_by(Session.started_at.desc()).limit(1)
            if current_session_id:
                stmt = stmt.where(Session.id != current_session_id)
            last_session_row = session.scalars(stmt).first()

            unreconciled_trades = session.scalars(
                select(Trade)
                .where(Trade.status == STATUS_PLACED)
                .order_by(Trade.timestamp.desc())
                .limit(10)
            ).all()

            return {
                "last_session": last_session_row.to_dict() if last_session_row else None,
                "unreconciled_trades": [t.to_dict() for t in unreconciled_trades],
            }

    # ── TUI query methods ─────────────────────────────────────

    def get_recommendations(
        self,
        *,
        status: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Filtered group query for TUI screens. Returns groups with nested legs."""
        with self._session_factory() as session:
            stmt = select(RecommendationGroup).order_by(RecommendationGroup.created_at.desc())
            if status:
                stmt = stmt.where(RecommendationGroup.status == status)
            if session_id:
                stmt = stmt.where(RecommendationGroup.session_id == session_id)
            stmt = stmt.limit(limit)
            groups = session.scalars(stmt).all()
            return [g.to_dict() for g in groups]

    def get_trades(
        self,
        *,
        session_id: str | None = None,
        exchange: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Filtered trade query for TUI screens."""
        with self._session_factory() as session:
            stmt = select(Trade).order_by(Trade.timestamp.desc())
            if session_id:
                stmt = stmt.where(Trade.session_id == session_id)
            if exchange:
                stmt = stmt.where(Trade.exchange == exchange)
            if status:
                stmt = stmt.where(Trade.status == status)
            stmt = stmt.limit(limit)
            trades = session.scalars(stmt).all()
            return [t.to_dict() for t in trades]

    def get_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Session listing for history screen with derived rec/trade counts."""
        rec_count_sq = (
            select(func.count(RecommendationGroup.id))
            .where(RecommendationGroup.session_id == Session.id)
            .correlate(Session)
            .scalar_subquery()
            .label("recommendations_made")
        )
        trade_count_sq = (
            select(func.count(Trade.id))
            .where(Trade.session_id == Session.id)
            .correlate(Session)
            .scalar_subquery()
            .label("trades_placed")
        )
        with self._session_factory() as session:
            stmt = (
                select(Session, rec_count_sq, trade_count_sq)
                .order_by(Session.started_at.desc())
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    **row[0].to_dict(),
                    "recommendations_made": row[1],
                    "trades_placed": row[2],
                }
                for row in rows
            ]

    # ── Backup ────────────────────────────────────────────────

    def backup_if_needed(
        self,
        backup_dir: str | Path,
        max_age_hours: int = 24,
        max_backups: int = 7,
    ) -> str | None:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        import time

        backups = sorted(backup_dir.glob("agent_*.db"), key=lambda p: p.stat().st_mtime)
        if backups:
            age_hours = (time.time() - backups[-1].stat().st_mtime) / 3600
            if age_hours < max_age_hours:
                return None

        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"agent_{ts}.db"

        import shutil

        # Checkpoint WAL into main DB, then file-copy. Much faster than
        # sqlite3.backup() for large databases, and safe when no other
        # writers are active (enforced by EXCLUSIVE locking mode).
        # Dispose pool to release EXCLUSIVE file lock before copying.
        with self._engine.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        self._engine.dispose()
        shutil.copy2(self.db_path, backup_path)

        logger.info("Database backup created: %s", backup_path)

        backups = sorted(backup_dir.glob("agent_*.db"), key=lambda p: p.stat().st_mtime)
        pruned = len(backups) - max_backups
        for old in backups[:-max_backups]:
            old.unlink()
        if pruned > 0:
            logger.debug("Pruned %d old backups", pruned)

        return str(backup_path)


def run_backup() -> None:
    """CLI entry point: force a database backup."""
    from .config import load_configs
    from .logging_config import setup_logging

    setup_logging()

    _, _, tc = load_configs()
    db = AgentDatabase(tc.db_path)
    try:
        result = db.backup_if_needed(tc.backup_dir, max_age_hours=0)
        logger.info("Backup: %s", result)
    finally:
        db.close()


def run_startup() -> None:
    """CLI entry point: dump session state JSON."""
    import json

    from .config import load_configs
    from .logging_config import setup_logging

    setup_logging()

    _, _, tc = load_configs()
    db = AgentDatabase(tc.db_path)
    try:
        state = db.get_session_state()
        print(json.dumps(state, indent=2, default=str))  # noqa: T201
    finally:
        db.close()
