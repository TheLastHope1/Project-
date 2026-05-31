from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/polymarket_edge"

    GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"
    CLOB_API_BASE: str = "https://clob.polymarket.com"
    DATA_API_BASE: str = "https://data-api.polymarket.com"
    MARKET_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    POLL_INTERVAL_SECONDS: int = 30
    REQUEST_TIMEOUT_SECONDS: float = 15
    MAX_MARKETS: int = 500
    MAX_TOKENS: int = 1000

    DEFAULT_FEE: float = 0.0
    DEFAULT_LATENCY_COST: float = 0.002
    DEFAULT_ADVERSE_SELECTION_COST: float = 0.004
    MODEL_SIGMA_DEFAULT: float = 0.05
    Z_ALPHA: float = 1.96

    DATA_MODE: Literal["public"] = "public"
    TRADING_MODE: Literal["paper", "live_tiny"] = "paper"

    LIVE_TRADING_ENABLED: bool = False
    REAL_MONEY_ACKNOWLEDGED: bool = False
    REQUIRE_MANUAL_CONFIRMATION: bool = True
    ALLOW_LIVE_LOOP: bool = False
    ALLOW_MARKET_ORDERS: bool = False
    LIVE_TRADING_HALTED: bool = False

    MAX_ORDER_USD: float = 1.0
    MAX_DAILY_VOLUME_USD: float = 5.0
    MAX_DAILY_LOSS_USD: float = 2.0
    MAX_OPEN_EXPOSURE_USD: float = 5.0
    MAX_MARKET_EXPOSURE_USD: float = 1.0
    MAX_POSITION_FRACTION: float = 0.01

    MIN_NET_EDGE: float = 0.03
    MAX_SPREAD: float = 0.05
    MAX_MODEL_SIGMA: float = 0.08
    MAX_ORDERBOOK_STALENESS_SECONDS: float = 5
    LIVE_ORDER_TIMEOUT_SECONDS: int = 60

    MIN_PAPER_TRADES_BEFORE_LIVE: int = 50
    MIN_PAPER_WIN_RATE: float = 0.52
    MIN_PAPER_AVG_EDGE: float = 0.01
    MIN_PAPER_REALIZED_PNL: float = 0
    MIN_PAPER_EDGE_PNL_CORRELATION: float = 0.1
    OVERRIDE_PROMOTION_CHECK: bool = False

    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_FUNDER_ADDRESS: str = ""
    POLYMARKET_SIGNATURE_TYPE: str = ""
    POLYMARKET_API_KEY: str = ""
    POLYMARKET_API_SECRET: str = ""
    POLYMARKET_API_PASSPHRASE: str = ""
    POLYMARKET_EDGE_API_TOKEN: str = ""

    # --- News / breaking-signal ingestion -------------------------------
    # Comma-separated enabled sources. "rss" and "gdelt" are keyless and on by
    # default; "newsapi" and "twitter" activate only when their key is set.
    NEWS_SOURCES: str = "rss,gdelt"
    NEWS_LOOKBACK_HOURS: float = 24.0
    NEWS_MAX_ITEMS_PER_SOURCE: int = 100
    # Extra Google-News / GDELT query terms (comma-separated). Empty = use the
    # default breaking-news topic queries baked into the RSS/GDELT clients.
    NEWS_QUERY_TERMS: str = ""
    # Deterministic linking knobs.
    NEWS_MIN_OVERLAP: int = 1
    NEWS_MAX_CANDIDATES_PER_ITEM: int = 5
    # Relevance engine: "hybrid" | "deterministic" | "llm".
    NEWS_RELEVANCE_MODE: str = "hybrid"
    # Cost guard: cap how many news items get LLM adjudication per scan.
    NEWS_LLM_MAX_ITEMS: int = 25
    # A news signal must clear these to count as an edge candidate.
    NEWS_MIN_RELEVANCE: float = 0.5
    NEWS_MIN_CONFIDENCE: float = 0.5
    NEWS_EDGE_MIN_NET: float = 0.05

    # Keys for optional sources / LLM. Blank disables that capability.
    NEWSAPI_KEY: str = ""
    X_BEARER_TOKEN: str = ""
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://") and "+psycopg" not in value:
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @property
    def env_path(self) -> Path:
        return Path(".env.local")

    @property
    def news_query_terms(self) -> list[str]:
        return [t.strip() for t in self.NEWS_QUERY_TERMS.split(",") if t.strip()]

    @property
    def enabled_news_sources(self) -> list[str]:
        """Sources that are both requested and actually usable.

        "rss"/"gdelt" are keyless. "newsapi" needs NEWSAPI_KEY; "twitter"
        needs X_BEARER_TOKEN -- they are silently dropped if their key is
        absent so the pipeline never fails closed on a missing optional key.
        """
        requested = [s.strip().lower() for s in self.NEWS_SOURCES.split(",") if s.strip()]
        usable: list[str] = []
        for source in requested:
            if source == "newsapi" and not self.NEWSAPI_KEY:
                continue
            if source == "twitter" and not self.X_BEARER_TOKEN:
                continue
            usable.append(source)
        return usable

    @property
    def llm_relevance_enabled(self) -> bool:
        return self.NEWS_RELEVANCE_MODE in ("hybrid", "llm") and bool(self.ANTHROPIC_API_KEY)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
