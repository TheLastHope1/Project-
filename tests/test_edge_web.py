from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from polymarket_edge.config import reload_settings
from polymarket_edge.db.models import Base, EdgeSnapshot, KillSwitchEvent, Market, OrderbookSnapshot, Token
from polymarket_edge.db.session import make_engine
from polymarket_edge.trading.kill_switch import disable_live
from polymarket_edge.web.app import create_app


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    yield
    reload_settings()


def _client(tmp_path: Path, monkeypatch, api_token: str | None = None) -> TestClient:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'web.db'}")
    if api_token is None:
        monkeypatch.delenv("POLYMARKET_EDGE_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("POLYMARKET_EDGE_API_TOKEN", api_token)
    reload_settings()
    Base.metadata.create_all(make_engine())
    return TestClient(create_app())


def _client_without_schema(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.delenv("POLYMARKET_EDGE_API_TOKEN", raising=False)
    reload_settings()
    return TestClient(create_app())


def _seed_edge(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.db'}")
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime.now(UTC)
    session.add(Market(market_id="m1", active=True, closed=False, raw_json={}))
    session.add(Token(token_id="yes", market_id="m1", outcome="YES", outcome_index=0, raw_json={}))
    session.add(
        OrderbookSnapshot(
            token_id="yes",
            timestamp=now,
            best_bid=0.48,
            best_ask=0.5,
            mid=0.49,
            spread=0.02,
            bid_depth=[],
            ask_depth=[],
            raw_json={},
        )
    )
    session.add(
        EdgeSnapshot(
            market_id="m1",
            token_id="yes",
            timestamp=now,
            side="BUY",
            p_hat=0.7,
            sigma_p=0.01,
            bid=0.48,
            ask=0.5,
            raw_edge=0.2,
            total_cost=0.01,
            net_edge=0.19,
            kelly_size=1.0,
            action="BUY",
            raw_json={},
        )
    )
    session.commit()
    session.close()


def test_web_public_status_and_edges(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_edge(tmp_path)

    health = client.get("/health")
    status = client.get("/api/status")
    edges = client.get("/api/edges?limit=5")

    assert health.json() == {"ok": True}
    assert status.json()["active_markets"] == 1
    assert status.json()["paper_wallet"]["starting_cash"] == 1000
    assert edges.json()["edges"][0]["token_id"] == "yes"


def _seed_logical_ladder(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.db'}")
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime.now(UTC)
    end = datetime(2026, 12, 31, tzinfo=UTC)
    for mid_id, question, yes_bid, yes_ask in [
        ("m100", "Will BTC reach $100k by 2026?", 0.60, 0.62),
        ("m90", "Will BTC reach $90k by 2026?", 0.48, 0.50),
    ]:
        session.add(
            Market(market_id=mid_id, event_id="evt", question=question, active=True, closed=False, end_date=end, raw_json={})
        )
        session.add(Token(token_id=f"{mid_id}-yes", market_id=mid_id, outcome="Yes", outcome_index=0, raw_json={}))
        session.add(
            OrderbookSnapshot(
                token_id=f"{mid_id}-yes",
                timestamp=now,
                best_bid=yes_bid,
                best_ask=yes_ask,
                mid=(yes_bid + yes_ask) / 2,
                spread=yes_ask - yes_bid,
                bid_depth=[{"price": yes_bid, "size": 50}],
                ask_depth=[{"price": yes_ask, "size": 50}],
                raw_json={},
            )
        )
    session.commit()
    session.close()


def test_web_logical_arb_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_logical_ladder(tmp_path)

    response = client.get("/api/logical-arb")
    assert response.status_code == 200
    body = response.json()
    assert body["locked"] == 1
    assert body["candidates"][0]["arb_type"] == "LOCKED"
    assert body["candidates"][0]["strong_market_id"] == "m100"

    locked_only = client.get("/api/logical-arb?locked_only=true")
    assert locked_only.json()["count"] == 1


def test_web_status_handles_uninitialized_database(tmp_path, monkeypatch):
    client = _client_without_schema(tmp_path, monkeypatch)

    health = client.get("/health")
    status = client.get("/api/status")
    index = client.get("/")

    assert health.json() == {"ok": True}
    assert status.status_code == 200
    assert status.json()["database_initialized"] is False
    assert index.status_code == 200


def test_web_admin_disabled_without_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/admin/init-db")

    assert response.status_code == 503


def test_web_admin_requires_configured_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, api_token="secret-token")

    bad = client.post("/api/admin/init-db", headers={"x-api-token": "wrong"})
    good = client.post("/api/admin/init-db", headers={"x-api-token": "secret-token"})

    assert bad.status_code == 401
    assert good.status_code == 200
    assert good.json() == {"ok": True}


def test_web_paper_wallet_and_reset_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, api_token="secret-token")

    wallet = client.get("/api/paper-wallet")
    reset = client.post(
        "/api/admin/paper-reset?starting_cash=500",
        headers={"x-api-token": "secret-token"},
    )

    assert wallet.status_code == 200
    assert wallet.json()["starting_cash"] == 1000
    assert reset.status_code == 200
    assert reset.json()["cash_balance"] == 500


def test_web_kill_switch_records_event(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, api_token="secret-token")

    response = client.post(
        "/api/admin/kill-switch",
        headers={"x-api-token": "secret-token"},
        json={"reason": "test halt"},
    )

    assert response.status_code == 200
    assert response.json()["live_trading_halted"] is True

    engine = make_engine(f"sqlite:///{tmp_path / 'web.db'}")
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        event = session.execute(select(KillSwitchEvent)).scalar_one()
        assert event.reason == "test halt"
        assert event.raw_json["cancel_all"] == "dry-run"
    finally:
        session.close()


def test_disable_live_returns_false_when_env_file_cannot_be_written(tmp_path, monkeypatch):
    def raise_os_error(*_args, **_kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "touch", raise_os_error)

    assert disable_live(tmp_path / ".env.local") is False
