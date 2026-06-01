"""Deterministic news -> market linker (recall step).

Builds an inverted index over market questions, then for each news item
unions the markets sharing any token and scores them by weighted overlap
(proper-noun entity matches count far more than incidental keyword matches).
This is intentionally high-recall: it produces a tight shortlist that the
relevance engine (deterministic or LLM) then adjudicates for precision and
direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from polymarket_edge.news.entities import Extracted, extract

_ENTITY_WEIGHT = 3.0
_KEYWORD_WEIGHT = 1.0


@dataclass
class MarketDoc:
    market_id: str
    question: str
    event_id: str | None
    entities: set[str]
    keywords: set[str]
    tokens: set[str] = field(default_factory=set)


def build_market_doc(market: Any) -> MarketDoc | None:
    """Build a MarketDoc from a Market row (or any object with market_id /
    question / event_id). Returns None if there is no question text."""
    question = getattr(market, "question", None)
    if not question:
        return None
    title = getattr(market, "event_title", None) or ""
    ex = extract(f"{question}\n{title}")
    return MarketDoc(
        market_id=str(getattr(market, "market_id", "")),
        question=question,
        event_id=getattr(market, "event_id", None),
        entities=set(ex.entities),
        keywords=ex.keywords,
        tokens=ex.tokens(),
    )


def build_index(docs: list[MarketDoc]) -> dict[str, set[str]]:
    """token -> set of market_ids containing it."""
    index: dict[str, set[str]] = {}
    for doc in docs:
        for token in doc.tokens:
            index.setdefault(token, set()).add(doc.market_id)
    return index


@dataclass
class Candidate:
    market_id: str
    question: str
    score: float
    shared_entities: list[str]
    shared_keywords: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "question": self.question,
            "score": round(self.score, 3),
            "shared_entities": self.shared_entities,
            "shared_keywords": self.shared_keywords,
        }


def shortlist(
    news: Extracted,
    docs_by_id: dict[str, MarketDoc],
    index: dict[str, set[str]],
    *,
    max_candidates: int = 5,
    min_overlap: int = 1,
) -> list[Candidate]:
    """Rank candidate markets for one news item.

    Qualifies a market when it shares at least one proper-noun entity, or at
    least ``max(2, min_overlap)`` keywords (entities are far more diagnostic
    than incidental shared words like "win" or "2026").
    """
    news_tokens = news.tokens()
    if not news_tokens:
        return []

    candidate_ids: set[str] = set()
    for token in news_tokens:
        candidate_ids.update(index.get(token, ()))

    news_entities = set(news.entities)
    keyword_floor = max(2, min_overlap)

    candidates: list[Candidate] = []
    for market_id in candidate_ids:
        doc = docs_by_id.get(market_id)
        if doc is None:
            continue
        shared_entities = sorted(news_entities & doc.entities)
        shared_keywords = sorted((news.keywords & doc.keywords) - set(shared_entities))
        if not shared_entities and len(shared_keywords) < keyword_floor:
            continue
        score = _ENTITY_WEIGHT * len(shared_entities) + _KEYWORD_WEIGHT * len(shared_keywords)
        candidates.append(
            Candidate(
                market_id=market_id,
                question=doc.question,
                score=score,
                shared_entities=shared_entities,
                shared_keywords=shared_keywords,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:max_candidates]
