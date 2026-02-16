"""SQLAlchemy ORM models — canonical schema definition for all 6 tables."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    def to_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# ── Market Snapshots ──────────────────────────────────────────


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="collector")
    exchange: Mapped[str] = mapped_column(Text, nullable=False, server_default="kalshi")
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
    exchange: Mapped[str] = mapped_column(Text, primary_key=True, server_default="kalshi")
    series_ticker: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    mutually_exclusive: Mapped[int | None] = mapped_column(Integer)
    last_updated: Mapped[str | None] = mapped_column(Text)
    markets_json: Mapped[str | None] = mapped_column(Text)


# ── Trades ────────────────────────────────────────────────────


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    ended_at: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    trades_placed: Mapped[int] = mapped_column(Integer, server_default="0")
    recommendations_made: Mapped[int] = mapped_column(Integer, server_default="0")
    pnl_usd: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("idx_sessions_ended_at", "ended_at"),)


# ── Recommendation Groups ────────────────────────────────────


class RecommendationGroup(Base):
    __tablename__ = "recommendation_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey("sessions.id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    thesis: Mapped[str | None] = mapped_column(Text)
    equivalence_notes: Mapped[str | None] = mapped_column(Text)
    estimated_edge_pct: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str | None] = mapped_column(Text, server_default="pending")
    expires_at: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[str | None] = mapped_column(Text)
    total_exposure_usd: Mapped[float | None] = mapped_column(Float)
    computed_edge_pct: Mapped[float | None] = mapped_column(Float)
    computed_fees_usd: Mapped[float | None] = mapped_column(Float)

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


class RecommendationLeg(Base):
    __tablename__ = "recommendation_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    status: Mapped[str | None] = mapped_column(Text, server_default="pending")
    order_id: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[str | None] = mapped_column(Text)
    is_maker: Mapped[bool | None] = mapped_column(Boolean)
    fill_price_cents: Mapped[int | None] = mapped_column(Integer)
    fill_quantity: Mapped[int | None] = mapped_column(Integer)
    orderbook_snapshot_json: Mapped[str | None] = mapped_column(Text)

    group: Mapped[RecommendationGroup] = relationship(back_populates="legs")

    __table_args__ = (Index("idx_leg_group", "group_id"),)
