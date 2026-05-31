from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from polymarket_edge.config import get_settings, reload_settings
from polymarket_edge.db.models import Base, EdgeSnapshot, Market, NewsItem, NewsSignal, OrderbookSnapshot, Token
from polymarket_edge.db.session import make_engine
from polymarket_edge.news import relevance
from polymarket_edge.news.edge import scan_news_edges
from polymarket_edge.news.linker import Candidate
from polymarket_edge.news.models import RawNewsItem


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    reload_settings()


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'edge.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ---- relevance adjudicator ----------------------------------------------


def test_deterministic_mode_yields_no_direction(monkeypatch):
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "deterministic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reload_settings()
    news = RawNewsItem(source="rss", title="Trump rally")
    cands = [Candidate("m1", "Will Trump win?", 3.0, ["trump"], [])]
    verdicts = relevance.adjudicate(news, cands, get_settings())
    assert len(verdicts) == 1
    assert verdicts[0].direction == "NONE"
    assert verdicts[0].model == "deterministic"
    assert verdicts[0].implied_p is None


def test_hybrid_falls_back_to_deterministic_without_key(monkeypatch):
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "hybrid")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reload_settings()
    news = RawNewsItem(source="rss", title="Trump rally")
    cands = [Candidate("m1", "Will Trump win?", 3.0, ["trump"], [])]
    verdicts = relevance.adjudicate(news, cands, get_settings())
    assert verdicts[0].model == "deterministic"


def test_llm_verdicts_parse_mocked_response(monkeypatch):
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    reload_settings()

    payload = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "verdicts": [
                            {
                                "market_id": "m1",
                                "relevant": True,
                                "direction": "YES_DOWN",
                                "confidence": 0.8,
                                "implied_probability": 0.2,
                                "rationale": "Health news lowers resignation odds.",
                            }
                        ]
                    }
                ),
            }
        ],
        "usage": {"cache_read_input_tokens": 0, "input_tokens": 500, "output_tokens": 60},
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    client = MagicMock()
    client.post.return_value = resp
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    monkeypatch.setattr(relevance.httpx, "Client", lambda *a, **k: client)

    news = RawNewsItem(source="bbc", title="Trump in excellent health")
    cands = [Candidate("m1", "Will Trump resign by 2026?", 3.0, ["trump"], [])]
    verdicts = relevance.adjudicate(news, cands, get_settings())
    assert len(verdicts) == 1
    assert verdicts[0].direction == "YES_DOWN"
    assert verdicts[0].implied_p == 0.2
    assert verdicts[0].confidence == 0.8
    assert verdicts[0].model == get_settings().ANTHROPIC_MODEL


def test_llm_request_shape_has_cache_control_and_schema(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "llm")
    reload_settings()
    captured = {}

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"content": [{"type": "text", "text": '{"verdicts": []}'}], "usage": {}}

    def fake_post(url, headers=None, json=None):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return resp

    client = MagicMock()
    client.post.side_effect = fake_post
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    monkeypatch.setattr(relevance.httpx, "Client", lambda *a, **k: client)

    relevance.llm_verdicts(
        RawNewsItem(source="rss", title="x"),
        [Candidate("m1", "q", 1.0, [], ["x"])],
        get_settings(),
    )
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["body"]["output_config"]["format"]["type"] == "json_schema"


# ---- news -> edge end to end (deterministic LLM stub) -------------------


def _seed_market_with_book(session, *, yes_ask=0.30, yes_bid=0.27):
    session.add(Market(market_id="m1", event_id="e1", question="Will Trump resign by 2026?",
                       active=True, closed=False, raw_json={}))
    session.add(Token(token_id="m1-yes", market_id="m1", outcome="Yes", outcome_index=0, raw_json={}))
    session.add(OrderbookSnapshot(
        token_id="m1-yes", timestamp=datetime.now(UTC),
        best_bid=yes_bid, best_ask=yes_ask, mid=(yes_bid + yes_ask) / 2, spread=yes_ask - yes_bid,
        bid_depth=[{"price": yes_bid, "size": 100}], ask_depth=[{"price": yes_ask, "size": 100}],
        raw_json={},
    ))
    session.add(NewsItem(
        dedup_hash="h1", source="bbc", source_name="BBC",
        title="Trump resignation imminent, sources say",
        fetched_at=datetime.now(UTC), entities=["trump"], raw_json={},
    ))
    session.commit()


def test_scan_news_edges_creates_edge_from_news(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "deterministic")  # avoid real LLM
    reload_settings()
    session = _session(tmp_path)
    _seed_market_with_book(session, yes_ask=0.30)

    # Stub adjudicate to return a strong YES_UP verdict with implied_p well
    # above the 0.30 ask, so score_market produces a BUY edge.
    from polymarket_edge.news.relevance import RelevanceVerdict

    def fake_adjudicate(news, candidates, settings=None):
        return [
            RelevanceVerdict(
                market_id="m1", relevant=True, direction="YES_UP",
                confidence=0.9, implied_p=0.75,
                rationale="Resignation reported imminent.", model="stub",
            )
        ]

    monkeypatch.setattr("polymarket_edge.news.edge.adjudicate", fake_adjudicate)

    summary = scan_news_edges(session)
    session.commit()

    assert summary.signals_saved == 1
    assert summary.actionable_edges == 1
    assert summary.edges[0]["action"] == "BUY"
    assert summary.edges[0]["direction"] == "YES_UP"

    # NewsSignal + news-sourced EdgeSnapshot persisted.
    assert session.query(NewsSignal).count() == 1
    edge = session.execute(select(EdgeSnapshot)).scalar_one()
    assert edge.raw_json["source"] == "news"
    assert edge.action == "BUY"
    assert edge.p_hat == 0.75


def test_scan_news_edges_direction_mismatch_suppressed(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "deterministic")
    reload_settings()
    session = _session(tmp_path)
    _seed_market_with_book(session, yes_ask=0.30)

    from polymarket_edge.news.relevance import RelevanceVerdict

    # YES_DOWN but implied_p (0.75) is ABOVE the ask -> score_market says BUY,
    # which contradicts the YES_DOWN read -> the edge must be suppressed.
    def fake_adjudicate(news, candidates, settings=None):
        return [RelevanceVerdict("m1", True, "YES_DOWN", 0.9, 0.75, "x", "stub")]

    monkeypatch.setattr("polymarket_edge.news.edge.adjudicate", fake_adjudicate)
    summary = scan_news_edges(session)
    session.commit()
    assert summary.signals_saved == 1       # signal still recorded
    assert summary.actionable_edges == 0     # but no contradictory edge


def test_scan_news_edges_low_confidence_no_edge(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_RELEVANCE_MODE", "deterministic")
    monkeypatch.setenv("NEWS_MIN_CONFIDENCE", "0.5")
    reload_settings()
    session = _session(tmp_path)
    _seed_market_with_book(session, yes_ask=0.30)

    from polymarket_edge.news.relevance import RelevanceVerdict

    def fake_adjudicate(news, candidates, settings=None):
        return [RelevanceVerdict("m1", True, "YES_UP", 0.2, 0.75, "x", "stub")]

    monkeypatch.setattr("polymarket_edge.news.edge.adjudicate", fake_adjudicate)
    summary = scan_news_edges(session)
    session.commit()
    assert summary.signals_saved == 1
    assert summary.actionable_edges == 0  # confidence 0.2 < 0.5 floor
