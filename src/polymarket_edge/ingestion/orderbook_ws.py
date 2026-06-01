from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import websockets
from sqlalchemy.orm import sessionmaker

from polymarket_edge.clients.clob import NormalizedOrderbook
from polymarket_edge.config import get_settings
from polymarket_edge.db.session import make_session_factory
from polymarket_edge.ingestion.orderbook_poller import active_token_ids, save_orderbook_snapshot
from polymarket_edge.logging import get_logger

log = get_logger(__name__)


@dataclass
class StreamSummary:
    subscribed_tokens: int
    messages_seen: int = 0
    snapshots_saved: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    message: str = ""


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_token_id(event: dict[str, Any]) -> str:
    return str(
        event.get("asset_id")
        or event.get("token_id")
        or event.get("market")
        or event.get("asset")
        or ""
    )


def _levels(raw_levels: Any, *, reverse: bool) -> list[dict[str, float]]:
    levels: list[dict[str, float]] = []
    if not isinstance(raw_levels, list):
        return levels
    for level in raw_levels:
        if isinstance(level, dict):
            price = _float_or_none(level.get("price") or level.get("p"))
            size = _float_or_none(level.get("size") or level.get("s"))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _float_or_none(level[0])
            size = _float_or_none(level[1])
        else:
            continue
        if price is not None and size is not None and price > 0 and size > 0:
            levels.append({"price": price, "size": size})
    return sorted(levels, key=lambda row: row["price"], reverse=reverse)


def orderbook_from_ws_event(event: dict[str, Any]) -> NormalizedOrderbook | None:
    """Normalize public CLOB market-channel events into snapshot rows.

    Full ``book`` events include depth. Some incremental events only include
    top-of-book fields; those still become snapshots, but with empty depth.
    """
    event_type = str(event.get("event_type") or event.get("type") or "")
    token_id = _event_token_id(event)
    if not token_id:
        return None
    if event_type == "book" or "bids" in event or "asks" in event:
        bids = _levels(event.get("bids") or event.get("buy") or [], reverse=True)
        asks = _levels(event.get("asks") or event.get("sell") or [], reverse=False)
        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
        spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
        return NormalizedOrderbook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            mid=mid,
            spread=spread,
            timestamp=datetime.now(UTC),
            raw_json=event,
        )
    best_bid = _float_or_none(event.get("best_bid") or event.get("bid"))
    best_ask = _float_or_none(event.get("best_ask") or event.get("ask"))
    if best_bid is None and best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
    spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
    return NormalizedOrderbook(
        token_id=token_id,
        bids=[],
        asks=[],
        best_bid=best_bid,
        best_ask=best_ask,
        mid=mid,
        spread=spread,
        timestamp=datetime.now(UTC),
        raw_json=event,
    )


def _decode_events(message: str) -> list[dict[str, Any]]:
    if message in ("PONG", "PING", ""):
        return []
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        log.warning("ws_json_decode_failed")
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


async def _heartbeat(ws: Any) -> None:
    while True:
        await asyncio.sleep(10)
        await ws.send("PING")


async def stream_orderbooks(
    token_ids: list[str],
    *,
    max_messages: int = 50,
    persist: bool = False,
    session_factory: sessionmaker | None = None,
) -> StreamSummary:
    settings = get_settings()
    token_ids = [str(token_id) for token_id in token_ids if token_id]
    summary = StreamSummary(subscribed_tokens=len(token_ids))
    if not token_ids:
        summary.message = "no active token ids available to subscribe"
        return summary

    async with websockets.connect(settings.MARKET_WS_URL, ping_interval=None, close_timeout=5) as ws:
        await ws.send(json.dumps({
            "assets_ids": token_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }))
        heartbeat = asyncio.create_task(_heartbeat(ws))
        try:
            while summary.messages_seen < max_messages:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=settings.REQUEST_TIMEOUT_SECONDS + 10)
                except TimeoutError:
                    summary.message = "market websocket stream timed out waiting for events"
                    break
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                events = _decode_events(str(message))
                if not events:
                    continue
                summary.messages_seen += len(events)
                for event in events:
                    event_type = str(event.get("event_type") or event.get("type") or "unknown")
                    summary.event_counts[event_type] = summary.event_counts.get(event_type, 0) + 1
                    book = orderbook_from_ws_event(event)
                    if not persist or book is None or session_factory is None or not (book.bids or book.asks):
                        continue
                    with session_factory() as session:
                        save_orderbook_snapshot(session, book)
                        session.commit()
                    summary.snapshots_saved += 1
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
    if not summary.message:
        summary.message = "market websocket stream completed"
    return summary


async def stream_orderbooks_from_db(
    max_tokens: int = 200,
    max_messages: int = 50,
    persist: bool = False,
) -> StreamSummary:
    factory = make_session_factory()
    with factory() as session:
        token_ids = active_token_ids(session, limit=max_tokens)
    return await stream_orderbooks(
        token_ids,
        max_messages=max_messages,
        persist=persist,
        session_factory=factory if persist else None,
    )
