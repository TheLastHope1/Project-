"""Turn adjudicated news signals into news-driven edges.

The pipeline: latest news items -> deterministic shortlist of candidate
markets -> relevance adjudication (deterministic or LLM) -> persist
``NewsSignal`` rows -> for relevant, directional, confident signals with an
order book, run the existing ``edge_engine.score_market`` using the news
``implied_p`` as the independent ``p_hat``. Actionable results are persisted
as ``EdgeSnapshot`` rows tagged ``source=news`` so they flow into the same
paper-trade / backtest machinery as every other edge.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from polymarket_edge.arbitrage.logical_scanner import _latest_snapshots, _yes_token_by_market
from polymarket_edge.config import Settings, get_settings
from polymarket_edge.db.models import EdgeSnapshot, Market, NewsItem, NewsSignal
from polymarket_edge.logging import get_logger
from polymarket_edge.models.edge_engine import score_market
from polymarket_edge.news.entities import extract
from polymarket_edge.news.linker import build_index, build_market_doc, shortlist
from polymarket_edge.news.models import RawNewsItem
from polymarket_edge.news.relevance import adjudicate

log = get_logger(__name__)


@dataclass
class NewsEdge:
    news_id: int
    market_id: str
    token_id: str | None
    direction: str
    confidence: float
    implied_p: float
    best_bid: float | None
    best_ask: float | None
    action: str
    net_edge: float
    kelly_size: float
    headline: str
    rationale: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NewsEdgeSummary:
    news_items_considered: int = 0
    candidates_shortlisted: int = 0
    signals_saved: int = 0
    actionable_edges: int = 0
    edges: list[dict[str, Any]] = field(default_factory=list)


def _confidence_to_sigma(confidence: float, settings: Settings) -> float:
    """Map LLM confidence to a probability sigma for the cost model.

    High confidence -> low sigma -> lower cost penalty. Floored so even a
    maximally confident news read still carries some uncertainty.
    """
    base = settings.MODEL_SIGMA_DEFAULT
    return max(0.02, base + (1.0 - max(0.0, min(1.0, confidence))) * 0.20)


def _raw_from_row(row: NewsItem) -> RawNewsItem:
    return RawNewsItem(
        source=row.source,
        title=row.title,
        url=row.url,
        summary=row.summary,
        source_name=row.source_name,
        published_at=row.published_at,
        language=row.language,
    )


def scan_news_edges(
    session: Session,
    settings: Settings | None = None,
    max_items: int | None = None,
) -> NewsEdgeSummary:
    settings = settings or get_settings()
    summary = NewsEdgeSummary()

    markets = list(
        session.execute(
            select(Market).where(Market.active.is_(True), Market.closed.is_(False))
        ).scalars()
    )
    docs = [d for d in (build_market_doc(m) for m in markets) if d]
    docs_by_id = {d.market_id: d for d in docs}
    index = build_index(docs)
    if not index:
        return summary

    snapshots = _latest_snapshots(session)
    yes_tokens = _yes_token_by_market(session)

    cap = max_items or settings.NEWS_LLM_MAX_ITEMS
    news_rows = list(
        session.execute(
            select(NewsItem).order_by(desc(NewsItem.fetched_at)).limit(cap)
        ).scalars()
    )

    for row in news_rows:
        summary.news_items_considered += 1
        extracted = extract(f"{row.title}\n{row.summary or ''}")
        candidates = shortlist(
            extracted, docs_by_id, index,
            max_candidates=settings.NEWS_MAX_CANDIDATES_PER_ITEM,
            min_overlap=settings.NEWS_MIN_OVERLAP,
        )
        if not candidates:
            continue
        summary.candidates_shortlisted += len(candidates)

        verdicts = adjudicate(_raw_from_row(row), candidates, settings)
        for verdict in verdicts:
            if not verdict.relevant:
                continue
            token = yes_tokens.get(verdict.market_id)
            token_id = token.token_id if token else None
            snapshot = snapshots.get(token_id) if token_id else None

            # Persist the signal regardless of whether it clears the edge bar.
            session.add(
                NewsSignal(
                    news_id=row.id,
                    market_id=verdict.market_id,
                    token_id=token_id,
                    relevance=verdict.confidence,
                    direction=verdict.direction,
                    confidence=verdict.confidence,
                    implied_p=verdict.implied_p,
                    model=verdict.model,
                    rationale=verdict.rationale,
                    raw_json={"headline": row.title},
                )
            )
            summary.signals_saved += 1

            # An edge needs: a directional, confident verdict, an implied
            # probability, and a live order book to price against.
            if (
                verdict.implied_p is None
                or verdict.direction == "NONE"
                or verdict.confidence < settings.NEWS_MIN_CONFIDENCE
                or snapshot is None
            ):
                continue

            sigma = _confidence_to_sigma(verdict.confidence, settings)
            score = score_market(snapshot, verdict.implied_p, sigma, settings, n_markets=max(1, len(candidates)))
            if score.action == "NONE" or score.best_net_edge < settings.NEWS_EDGE_MIN_NET:
                continue

            # Direction sanity: a YES_UP news read should agree with a BUY
            # action (we expect YES to be underpriced), YES_DOWN with SELL.
            if (verdict.direction == "YES_UP" and score.action != "BUY") or (
                verdict.direction == "YES_DOWN" and score.action != "SELL"
            ):
                continue

            raw_edge = score.buy_raw_edge if score.action == "BUY" else score.sell_raw_edge
            session.add(
                EdgeSnapshot(
                    market_id=verdict.market_id,
                    token_id=token_id,
                    side=score.side,
                    p_hat=score.p_hat,
                    sigma_p=score.sigma,
                    bid=score.bid,
                    ask=score.ask,
                    raw_edge=raw_edge,
                    total_cost=score.total_cost,
                    net_edge=score.best_net_edge,
                    kelly_size=score.kelly_size,
                    action=score.action,
                    raw_json={
                        "source": "news",
                        "news_id": row.id,
                        "headline": row.title,
                        "direction": verdict.direction,
                        "rationale": verdict.rationale,
                        "model": verdict.model,
                    },
                )
            )
            summary.actionable_edges += 1
            summary.edges.append(
                NewsEdge(
                    news_id=row.id,
                    market_id=verdict.market_id,
                    token_id=token_id,
                    direction=verdict.direction,
                    confidence=verdict.confidence,
                    implied_p=verdict.implied_p,
                    best_bid=score.bid,
                    best_ask=score.ask,
                    action=score.action,
                    net_edge=score.best_net_edge,
                    kelly_size=score.kelly_size,
                    headline=row.title,
                    rationale=verdict.rationale,
                    model=verdict.model,
                ).to_dict()
            )

    summary.edges.sort(key=lambda e: e["net_edge"], reverse=True)
    log.info(
        "news_edges_scanned",
        items=summary.news_items_considered,
        candidates=summary.candidates_shortlisted,
        signals=summary.signals_saved,
        actionable=summary.actionable_edges,
    )
    return summary
