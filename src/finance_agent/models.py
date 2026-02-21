"""SQLAlchemy ORM models — canonical schema definition for all 9 tables."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .constants import EXCHANGE_KALSHI, STATUS_PENDING, STRATEGY_MANUAL


class Base(DeclarativeBase):
    def to_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── Market Snapshots ──────────────────────────────────────────


market_snapshot_id_seq = Sequence("market_snapshot_id_seq")


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(
        Integer,
        market_snapshot_id_seq,
        primary_key=True,
        server_default=market_snapshot_id_seq.next_value(),
    )
    captured_at: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="collector")
    exchange: Mapped[str] = mapped_column(Text, nullable=False, server_default=EXCHANGE_KALSHI)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    event_ticker: Mapped[str | None] = mapped_column(Text)
    series_ticker: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    yes_bid: Mapped[int | None] = mapped_column(Integer)
    yes_ask: Mapped[int | None] = mapped_column(Integer)
    no_bid: Mapped[int | None] = mapped_column(Integer)
    no_ask: Mapped[int | None] = mapped_column(Integer)
    last_price: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(Integer)
    volume_24h: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    spread_cents: Mapped[int | None] = mapped_column(Integer)
    mid_price_cents: Mapped[int | None] = mapped_column(Integer)
    implied_probability: Mapped[float | None] = mapped_column(Float)
    days_to_expiration: Mapped[float | None] = mapped_column(Float)
    close_time: Mapped[str | None] = mapped_column(Text)
    settlement_value: Mapped[int | None] = mapped_column(Integer)
    markets_in_event: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_snapshots_ticker_time", "ticker", "captured_at"),
        Index("idx_snapshots_series", "series_ticker"),
        Index("idx_snapshots_category", "category"),
        Index("idx_snapshots_latest", "status", "exchange", "ticker", "captured_at"),
    )


# ── Events ────────────────────────────────────────────────────


class Event(Base):
    __tablename__ = "events"

    event_ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    exchange: Mapped[str] = mapped_column(Text, primary_key=True, server_default=EXCHANGE_KALSHI)
    series_ticker: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    mutually_exclusive: Mapped[int | None] = mapped_column(Integer)
    last_updated: Mapped[str | None] = mapped_column(Text)
    markets_json: Mapped[str | None] = mapped_column(Text)


# ── Trades ────────────────────────────────────────────────────


trade_id_seq = Sequence("trade_id_seq")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(
        Integer, trade_id_seq, primary_key=True, server_default=trade_id_seq.next_value()
    )
    # NOTE: ForeignKey declarations kept for ORM relationship resolution.
    # DuckDB migration (0007) omits FK constraints at DDL level due to
    # DuckDB's limitation on UPDATE of FK-referenced parent tables.
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), nullable=False)
    leg_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recommendation_legs.id"))
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int | None] = mapped_column(Integer)
    order_type: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_trades_ticker", "ticker"),
        Index("idx_trades_session", "session_id"),
        Index("idx_trades_status", "status"),
    )


# ── Sessions ──────────────────────────────────────────────────


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    sdk_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Recommendation Groups ────────────────────────────────────


rec_group_id_seq = Sequence("rec_group_id_seq")


class RecommendationGroup(Base):
    __tablename__ = "recommendation_groups"

    id: Mapped[int] = mapped_column(
        Integer, rec_group_id_seq, primary_key=True, server_default=rec_group_id_seq.next_value()
    )
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    thesis: Mapped[str | None] = mapped_column(Text)
    equivalence_notes: Mapped[str | None] = mapped_column(Text)
    estimated_edge_pct: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(Text, server_default=STATUS_PENDING)
    expires_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[str | None] = mapped_column(Text)
    total_exposure_usd: Mapped[float | None] = mapped_column(Float)
    computed_edge_pct: Mapped[float | None] = mapped_column(Float)
    computed_fees_usd: Mapped[float | None] = mapped_column(Float)
    strategy: Mapped[str | None] = mapped_column(Text, server_default=STRATEGY_MANUAL)
    hypothetical_pnl_usd: Mapped[float | None] = mapped_column(Float)

    legs: Mapped[list[RecommendationLeg]] = relationship(
        back_populates="group",
        order_by="RecommendationLeg.leg_index",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_group_status", "status"),
        Index("idx_rec_session", "session_id"),
        Index("idx_group_created_at", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["legs"] = [leg.to_dict() for leg in self.legs]
        return d


# ── Recommendation Legs ──────────────────────────────────────


rec_leg_id_seq = Sequence("rec_leg_id_seq")


class RecommendationLeg(Base):
    __tablename__ = "recommendation_legs"

    id: Mapped[int] = mapped_column(
        Integer, rec_leg_id_seq, primary_key=True, server_default=rec_leg_id_seq.next_value()
    )
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendation_groups.id"), nullable=False
    )
    leg_index: Mapped[int] = mapped_column(Integer, server_default="0")
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    market_title: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    side: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer)
    price_cents: Mapped[int | None] = mapped_column(Integer)
    order_type: Mapped[str | None] = mapped_column(Text, server_default="limit")
    status: Mapped[str | None] = mapped_column(Text, server_default=STATUS_PENDING)
    order_id: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[str | None] = mapped_column(Text)
    is_maker: Mapped[bool | None] = mapped_column(Boolean)
    fill_price_cents: Mapped[int | None] = mapped_column(Integer)
    fill_quantity: Mapped[int | None] = mapped_column(Integer)
    orderbook_snapshot_json: Mapped[str | None] = mapped_column(Text)
    settlement_value: Mapped[int | None] = mapped_column(Integer)
    settled_at: Mapped[str | None] = mapped_column(Text)

    group: Mapped[RecommendationGroup] = relationship(back_populates="legs")

    __table_args__ = (Index("idx_leg_group", "group_id"),)


# ── Kalshi Daily History ─────────────────────────────────────


kalshi_daily_id_seq = Sequence("kalshi_daily_id_seq")


class KalshiDaily(Base):
    """Daily EOD market data from Kalshi's public S3 reporting bucket."""

    __tablename__ = "kalshi_daily"

    id: Mapped[int] = mapped_column(
        Integer,
        kalshi_daily_id_seq,
        primary_key=True,
        server_default=kalshi_daily_id_seq.next_value(),
    )
    date: Mapped[str] = mapped_column(Text, nullable=False)
    ticker_name: Mapped[str] = mapped_column(Text, nullable=False)
    report_ticker: Mapped[str] = mapped_column(Text, nullable=False)
    payout_type: Mapped[str | None] = mapped_column(Text)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    daily_volume: Mapped[int | None] = mapped_column(Integer)
    block_volume: Mapped[int | None] = mapped_column(Integer)
    high: Mapped[int | None] = mapped_column(Integer)
    low: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("date", "ticker_name", name="uq_kalshi_daily_date_ticker"),
        Index("idx_kalshi_daily_ticker", "ticker_name"),
        Index("idx_kalshi_daily_report", "report_ticker"),
    )


# ── Kalshi Market Metadata ───────────────────────────────────


class KalshiMarketMeta(Base):
    """Permanent market metadata catalog, never purged.

    Populated automatically during ``make collect`` from Kalshi API data.
    Provides titles/categories for joining with ``kalshi_daily`` history.
    """

    __tablename__ = "kalshi_market_meta"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    event_ticker: Mapped[str | None] = mapped_column(Text)
    series_ticker: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[str | None] = mapped_column(Text)
    last_seen: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_meta_series", "series_ticker"),
        Index("idx_meta_category", "category"),
    )


# ── Session Logs ─────────────────────────────────────────────

session_log_id_seq = Sequence("session_log_id_seq")


class SessionLog(Base):
    """Prose session summary captured by the server on session end."""

    __tablename__ = "session_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        session_log_id_seq,
        primary_key=True,
        server_default=session_log_id_seq.next_value(),
    )
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_session_log_session", "session_id"),)
