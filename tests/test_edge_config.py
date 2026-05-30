from __future__ import annotations

from polymarket_edge.config import Settings


def test_config_defaults_live_disabled():
    settings = Settings(_env_file=None)
    assert settings.DATA_MODE == "public"
    assert settings.TRADING_MODE == "paper"
    assert settings.LIVE_TRADING_ENABLED is False
    assert settings.REAL_MONEY_ACKNOWLEDGED is False
    assert settings.MAX_ORDER_USD == 1.0


def test_config_normalizes_postgres_url():
    settings = Settings(DATABASE_URL="postgres://u:p@localhost/db", _env_file=None)
    assert settings.DATABASE_URL == "postgresql+psycopg://u:p@localhost/db"

