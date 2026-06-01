from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dateutil import parser as dtparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from polymarket_edge.clients.gamma import GammaClient
from polymarket_edge.db.models import Event, Market, utc_now
from polymarket_edge.ingestion.token_mapper import upsert_tokens_for_market
from polymarket_edge.logging import get_logger

log = get_logger(__name__)


@dataclass
class DiscoverySummary:
    events_fetched: int = 0
    markets_upserted: int = 0
    tokens_extracted: int = 0
    failures: int = 0


def _str_or_none(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = dtparser.parse(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _event_id(raw: dict[str, Any]) -> str:
    return str(raw.get("id") or raw.get("event_id") or raw.get("slug") or "")


def _market_id(raw: dict[str, Any]) -> str:
    return str(raw.get("id") or raw.get("market_id") or raw.get("conditionId") or raw.get("condition_id") or "")


def _upsert_event(session: Session, raw: dict[str, Any]) -> Event | None:
    event_id = _event_id(raw)
    if not event_id:
        return None
    event = session.scalar(select(Event).where(Event.event_id == event_id))
    if event is None:
        event = Event(event_id=event_id)
        session.add(event)
    event.slug = _str_or_none(raw.get("slug"))
    event.title = _str_or_none(raw.get("title") or raw.get("name"))
    event.category = _str_or_none(raw.get("category") or raw.get("tag"))
    event.active = bool(raw.get("active", True))
    event.closed = bool(raw.get("closed", False))
    event.end_date = _dt(raw.get("endDate") or raw.get("end_date"))
    event.raw_json = raw
    event.updated_at = utc_now()
    return event


def _resolution_rules(raw: dict[str, Any]) -> str | None:
    for key in ("rules", "resolutionSource", "resolution_source", "description"):
        value = raw.get(key)
        if value:
            return str(value)
    return None


def _upsert_market(session: Session, raw: dict[str, Any], event_id: str | None = None) -> Market | None:
    market_id = _market_id(raw)
    if not market_id:
        return None
    market = session.scalar(select(Market).where(Market.market_id == market_id))
    if market is None:
        market = Market(market_id=market_id)
        session.add(market)
    market.event_id = _str_or_none(event_id or raw.get("eventId") or raw.get("event_id"))
    market.condition_id = _str_or_none(raw.get("conditionId") or raw.get("condition_id"))
    market.slug = _str_or_none(raw.get("slug"))
    market.question = _str_or_none(raw.get("question") or raw.get("title"))
    market.active = bool(raw.get("active", True))
    market.closed = bool(raw.get("closed", False))
    market.volume = _float(raw.get("volume24hr") or raw.get("volume_24hr") or raw.get("volume"))
    market.liquidity = _float(raw.get("liquidity"))
    market.end_date = _dt(raw.get("endDate") or raw.get("end_date_iso") or raw.get("end_date"))
    market.resolution_rules = _resolution_rules(raw)
    market.raw_json = raw
    market.updated_at = utc_now()
    return market


async def discover_markets(session: Session, max_events: int | None = None) -> DiscoverySummary:
    summary = DiscoverySummary()
    seen_markets: set[str] = set()
    async with GammaClient() as gamma:
        async for event_raw in gamma.iter_active_events(max_events=max_events):
            try:
                summary.events_fetched += 1
                event = _upsert_event(session, event_raw)
                event_id = event.event_id if event is not None else None
                markets = event_raw.get("markets") if isinstance(event_raw, dict) else None
                if isinstance(markets, list):
                    for market_raw in markets:
                        if not isinstance(market_raw, dict):
                            continue
                        market = _upsert_market(session, market_raw, event_id=event_id)
                        if market is None:
                            continue
                        seen_markets.add(market.market_id)
                        summary.markets_upserted += 1
                        session.flush()
                        summary.tokens_extracted += upsert_tokens_for_market(session, market)
            except Exception as exc:  # noqa: BLE001
                summary.failures += 1
                log.warning("event_discovery_failed", error=str(exc))

        fallback_limit = max_events or 500
        async for market_raw in gamma.iter_active_markets(max_markets=fallback_limit):
            try:
                market_id = _market_id(market_raw)
                if not market_id or market_id in seen_markets:
                    continue
                market = _upsert_market(session, market_raw)
                if market is None:
                    continue
                seen_markets.add(market.market_id)
                summary.markets_upserted += 1
                session.flush()
                summary.tokens_extracted += upsert_tokens_for_market(session, market)
            except Exception as exc:  # noqa: BLE001
                summary.failures += 1
                log.warning("market_discovery_failed", error=str(exc))
    return summary

