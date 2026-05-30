from __future__ import annotations

from polymarket_edge.config import Settings
from polymarket_edge.db.session import _engine_kwargs_for_url


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


def test_supabase_transaction_pooler_disables_prepared_statements():
    kwargs = _engine_kwargs_for_url(
        "postgresql+psycopg://postgres.ref:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    )
    assert kwargs["connect_args"]["prepare_threshold"] is None
