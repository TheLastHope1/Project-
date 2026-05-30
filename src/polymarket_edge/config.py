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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
