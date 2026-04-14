"""Database models for raw Reddit data and daily aggregated signals."""

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base ORM model."""


class RedditPostRaw(Base):
    __tablename__ = "reddit_posts_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_utc: Mapped[DateTime] = mapped_column(DateTime, index=True)
    author: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    selftext: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)
    num_comments: Mapped[int] = mapped_column(Integer)
    permalink: Mapped[str] = mapped_column(Text)


class RedditCommentRaw(Base):
    __tablename__ = "reddit_comments_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    post_id: Mapped[str] = mapped_column(String(32), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    created_utc: Mapped[DateTime] = mapped_column(DateTime, index=True)
    author: Mapped[str | None] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)


class DailyTickerSignal(Base):
    __tablename__ = "daily_ticker_signals"
    __table_args__ = (UniqueConstraint("trade_date", "ticker", name="uq_trade_date_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[Date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    mention_count: Mapped[int] = mapped_column(Integer)
    mention_velocity_z: Mapped[float] = mapped_column(Float)
    upvote_weighted_mentions: Mapped[float] = mapped_column(Float)
    engagement_score: Mapped[float] = mapped_column(Float)
    sentiment_score: Mapped[float] = mapped_column(Float)
    hype_score: Mapped[float] = mapped_column(Float)
