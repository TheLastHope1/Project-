from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


def json_type():
    return JSONB().with_variant(JSON(), "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    slug: Mapped[str | None] = mapped_column(String(512))
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class Market(Base, TimestampMixin):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    event_id: Mapped[str | None] = mapped_column(String(128), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(256), index=True)
    slug: Mapped[str | None] = mapped_column(String(512))
    question: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    liquidity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_rules: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)

    tokens: Mapped[list[Token]] = relationship(back_populates="market", cascade="all, delete-orphan")


class Token(Base, TimestampMixin):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    market_id: Mapped[str] = mapped_column(String(128), ForeignKey("markets.market_id"), nullable=False, index=True)
    condition_id: Mapped[str | None] = mapped_column(String(256), index=True)
    outcome: Mapped[str | None] = mapped_column(String(512))
    outcome_index: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)

    market: Mapped[Market] = relationship(back_populates="tokens")


class OrderbookSnapshot(Base):
    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[str] = mapped_column(String(256), ForeignKey("tokens.token_id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    best_bid: Mapped[float | None] = mapped_column(Float)
    best_ask: Mapped[float | None] = mapped_column(Float)
    mid: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    bid_depth: Mapped[list[dict[str, float]]] = mapped_column(json_type(), default=list, nullable=False)
    ask_depth: Mapped[list[dict[str, float]]] = mapped_column(json_type(), default=list, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("tx_hash", name="uq_trades_tx_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    token_id: Mapped[str | None] = mapped_column(String(256), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(256), index=True)
    market_slug: Mapped[str | None] = mapped_column(String(512))
    outcome: Mapped[str | None] = mapped_column(String(512))
    side: Mapped[str | None] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    proxy_wallet: Mapped[str | None] = mapped_column(String(256))
    tx_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class EdgeSnapshot(Base):
    __tablename__ = "edge_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    market_id: Mapped[str | None] = mapped_column(String(128), index=True)
    token_id: Mapped[str] = mapped_column(String(256), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    p_hat: Mapped[float | None] = mapped_column(Float)
    sigma_p: Mapped[float | None] = mapped_column(Float)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    raw_edge: Mapped[float | None] = mapped_column(Float)
    total_cost: Mapped[float | None] = mapped_column(Float)
    net_edge: Mapped[float | None] = mapped_column(Float)
    kelly_size: Mapped[float | None] = mapped_column(Float)
    action: Mapped[str] = mapped_column(String(16), default="NONE", nullable=False, index=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    market_id: Mapped[str | None] = mapped_column(String(128), index=True)
    token_id: Mapped[str] = mapped_column(String(256), index=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    limit_price: Mapped[float] = mapped_column(Float, nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    edge_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    simulated_fill_price: Mapped[float | None] = mapped_column(Float)
    simulated_pnl: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    market_id: Mapped[str | None] = mapped_column(String(128), index=True)
    token_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    shares: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realised_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class LiveOrder(Base):
    __tablename__ = "live_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    client_order_id: Mapped[str | None] = mapped_column(String(256), index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(256), index=True)
    market_id: Mapped[str | None] = mapped_column(String(128), index=True)
    token_id: Mapped[str | None] = mapped_column(String(256), index=True)
    side: Mapped[str | None] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    notional: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    edge_snapshot_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("edge_snapshots.id"))
    risk_snapshot_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)
    raw_request_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)
    raw_response_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class LiveFill(Base):
    __tablename__ = "live_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("live_orders.id"), index=True)
    exchange_trade_id: Mapped[str | None] = mapped_column(String(256))
    price: Mapped[float | None] = mapped_column(Float)
    size: Mapped[float | None] = mapped_column(Float)
    fee: Mapped[float | None] = mapped_column(Float)
    tx_hash: Mapped[str | None] = mapped_column(String(256))
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="warning", nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    cash_balance: Mapped[float | None] = mapped_column(Float)
    open_exposure: Mapped[float | None] = mapped_column(Float)
    realised_pnl: Mapped[float | None] = mapped_column(Float)
    unrealised_pnl: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class KillSwitchEvent(Base):
    __tablename__ = "kill_switch_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class NewsItem(Base):
    """A single normalized news/breaking item from any source.

    ``dedup_hash`` is a stable hash of the normalized title+url so the same
    story arriving from multiple feeds is stored once. ``entities`` is a list
    of extracted entity/keyword strings used for deterministic market linking.
    """

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # rss|gdelt|newsapi|twitter
    source_name: Mapped[str | None] = mapped_column(String(255))  # e.g. "Reuters"
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    entities: Mapped[dict[str, Any]] = mapped_column(json_type(), default=list, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)


class NewsSignal(Base):
    """A news item linked to a specific market with a directional read.

    ``implied_p`` is the news-derived probability estimate for the YES token
    (the independent p_hat the edge engine otherwise lacks). ``direction`` is
    YES_UP / YES_DOWN / NONE. ``model`` records provenance ("deterministic"
    or e.g. "claude-...") so signals can be audited and filtered.
    """

    __tablename__ = "news_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey("news_items.id"), nullable=False, index=True)
    market_id: Mapped[str | None] = mapped_column(String(128), index=True)
    token_id: Mapped[str | None] = mapped_column(String(256), index=True)
    relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), default="NONE", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    implied_p: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(64), default="deterministic", nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(json_type(), default=dict, nullable=False)
