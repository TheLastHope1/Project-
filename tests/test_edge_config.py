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
    assert settings.PAPER_STARTING_CASH_USD == 1000.0
    assert settings.PAPER_MAX_ORDER_USD == 25.0
    assert settings.resolved_news_llm_provider is None


def test_config_normalizes_postgres_url():
    settings = Settings(DATABASE_URL="postgres://u:p@localhost/db", _env_file=None)
    assert settings.DATABASE_URL == "postgresql+psycopg://u:p@localhost/db"


def test_supabase_transaction_pooler_disables_prepared_statements():
    kwargs = _engine_kwargs_for_url(
        "postgresql+psycopg://postgres.ref:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    )
    assert kwargs["connect_args"]["prepare_threshold"] is None


def test_deepseek_auto_provider_when_key_present(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.resolved_news_llm_provider == "deepseek"
    assert settings.resolved_news_llm_model == "deepseek-v4-pro"
