from __future__ import annotations

from pathlib import Path

from polymarket_edge.config import Settings
from polymarket_edge.secrets.manager import redacted_secret_status, write_env_value
from polymarket_edge.secrets.setup_wizard import ensure_env_file
from polymarket_edge.trading.risk import AccountState, EdgeState, MarketState, OrderIntent, RiskManager


def _order(order_type="limit", price=0.5, size=1.0):
    return OrderIntent(
        order_type=order_type,
        side="BUY",
        price=price,
        size=size,
        token_id="tok",
        market_id="m",
        client_order_id="cid",
        strategy_id="strategy",
    )


def _market(**overrides):
    data = dict(spread=0.01, sigma=0.01, staleness_seconds=0, token_stale=False, active=True, closed=False)
    data.update(overrides)
    return MarketState(**data)


def _account(**overrides):
    data = dict(market_exposure_after=0.0, open_exposure_after=0.0, daily_volume_after=0.0, daily_realized_pnl=0.0)
    data.update(overrides)
    return AccountState(**data)


def test_live_trading_disabled_by_default():
    decision = RiskManager(Settings(_env_file=None)).validate_order(_order(), _market(), _account(), EdgeState(0.5))
    assert not decision.approved
    assert any("LIVE_TRADING_ENABLED" in reason for reason in decision.reasons)


def test_risk_rejects_core_conditions():
    settings = Settings(
        LIVE_TRADING_ENABLED=True,
        REAL_MONEY_ACKNOWLEDGED=True,
        TRADING_MODE="live_tiny",
        _env_file=None,
    )
    manager = RiskManager(settings)
    assert not manager.validate_order(_order(price=2, size=2), _market(), _account(), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(spread=0.2), _account(), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(sigma=0.2), _account(), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(staleness_seconds=99), _account(), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(token_stale=True), _account(), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(active=False), _account(), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(), _account(daily_realized_pnl=-3), EdgeState(0.5)).approved
    assert not manager.validate_order(_order(), _market(), _account(), EdgeState(0.0)).approved


def test_risk_approves_when_all_guards_pass():
    settings = Settings(
        LIVE_TRADING_ENABLED=True,
        REAL_MONEY_ACKNOWLEDGED=True,
        TRADING_MODE="live_tiny",
        _env_file=None,
    )
    decision = RiskManager(settings).validate_order(_order(price=0.5, size=1), _market(), _account(), EdgeState(0.5))
    assert decision.approved


def test_secret_file_redaction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ensure_env_file(".env.local")
    write_env_value("POLYMARKET_API_SECRET", "super-secret-value", ".env.local")
    write_env_value("POLYMARKET_API_KEY", "abcdef123456", ".env.local")
    status = redacted_secret_status(".env.local")
    assert status["POLYMARKET_API_SECRET"] == "present:[REDACTED]"
    assert status["POLYMARKET_API_KEY"].endswith("3456")
    assert Path(".env.local").exists()

