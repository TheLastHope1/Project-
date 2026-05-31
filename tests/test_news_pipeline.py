from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

from polymarket_edge.config import reload_settings
from polymarket_edge.db.models import Base, NewsItem
from polymarket_edge.db.session import make_engine
from polymarket_edge.news.entities import extract
from polymarket_edge.news.ingest import persist_items
from polymarket_edge.news.linker import build_index, build_market_doc, shortlist
from polymarket_edge.news.models import RawNewsItem, canonical_url, clean_html, normalize_title


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    reload_settings()


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'news.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ---- models / normalization --------------------------------------------


def test_clean_html_strips_tags_and_entities():
    raw = '<a href="https://x/CBMiLONGB64">Fed holds rates</a>&nbsp;&mdash; Reuters'
    cleaned = clean_html(raw)
    assert "href" not in cleaned
    assert "CBMiLONGB64" not in cleaned  # URL slug gone with the tag
    assert "Fed holds rates" in cleaned


def test_normalize_title_strips_trailing_source():
    assert normalize_title("Bitcoin hits $150k - CoinDesk") == "Bitcoin hits $150k"


def test_canonical_url_drops_tracking_params():
    a = canonical_url("https://site.com/article?utm_source=x&id=1")
    b = canonical_url("http://site.com/article/")
    assert a == "site.com/article"
    assert b == "site.com/article"


def test_dedup_hash_collapses_same_story_across_sources():
    a = RawNewsItem(source="rss", title="Fed holds rates - Reuters", url="https://reuters.com/x?utm_source=g")
    b = RawNewsItem(source="gdelt", title="Fed holds rates", url="http://reuters.com/x/")
    assert a.dedup_hash == b.dedup_hash


# ---- entity extraction ---------------------------------------------------


def test_extract_entities_and_keywords():
    ex = extract("Federal Reserve holds rates as Donald Trump pressures Jerome Powell")
    assert "federal reserve" in ex.entities
    assert "donald trump" in ex.entities
    assert "rates" in ex.keywords


def test_extract_rejects_url_noise():
    # A base64-ish blob must not become an entity/keyword.
    blob = "CBMiLONGBASE64BLOBdeadbeefdeadbeefdeadbeefXY"
    ex = extract(f"Bitcoin surges {blob}")
    assert all(blob.lower() not in e for e in ex.entities)
    assert blob.lower() not in ex.keywords


# ---- ingest dedup --------------------------------------------------------


def test_persist_items_dedups_and_filters_stale(tmp_path):
    session = _session(tmp_path)
    now = datetime.now(UTC)
    cutoff = datetime(2026, 5, 1, tzinfo=UTC)
    items = [
        RawNewsItem(source="rss", title="Story A", url="https://s/a", published_at=now),
        RawNewsItem(source="gdelt", title="Story A", url="http://s/a/"),  # dup of A
        RawNewsItem(source="rss", title="Old story", url="https://s/old",
                    published_at=datetime(2026, 4, 1, tzinfo=UTC)),  # stale
        RawNewsItem(source="rss", title="Story B", url="https://s/b", published_at=now),
    ]
    summary = persist_items(session, items, cutoff)
    session.commit()
    assert summary.inserted == 2  # A and B
    assert summary.duplicates == 1
    assert summary.stale_skipped == 1
    assert session.query(NewsItem).count() == 2


def test_persist_items_idempotent_across_runs(tmp_path):
    session = _session(tmp_path)
    cutoff = datetime(2026, 5, 1, tzinfo=UTC)
    item = RawNewsItem(source="rss", title="Repeat", url="https://s/r",
                       published_at=datetime.now(UTC))
    persist_items(session, [item], cutoff)
    session.commit()
    summary2 = persist_items(session, [item], cutoff)
    session.commit()
    assert summary2.inserted == 0
    assert summary2.duplicates == 1


# ---- linker --------------------------------------------------------------


def _market(mid, question, event_id="evt"):
    m = MagicMock()
    m.market_id = mid
    m.question = question
    m.event_id = event_id
    m.event_title = None
    return m


def test_linker_shortlists_on_entity_overlap():
    markets = [
        _market("m1", "Will Donald Trump win the 2028 nomination?"),
        _market("m2", "Will Bitcoin reach $150k by 2026?"),
        _market("m3", "Will the Lakers win the NBA title?"),
    ]
    docs = [build_market_doc(m) for m in markets]
    docs_by_id = {d.market_id: d for d in docs}
    index = build_index(docs)

    ex = extract("Donald Trump holds rally ahead of 2028 run")
    cands = shortlist(ex, docs_by_id, index, max_candidates=5, min_overlap=1)
    ids = [c.market_id for c in cands]
    assert "m1" in ids
    assert "m2" not in ids and "m3" not in ids


def test_linker_returns_empty_when_no_overlap():
    docs = [build_market_doc(_market("m1", "Will the Lakers win the NBA title?"))]
    docs_by_id = {d.market_id: d for d in docs}
    index = build_index(docs)
    ex = extract("European Central Bank cuts rates")
    assert shortlist(ex, docs_by_id, index) == []
