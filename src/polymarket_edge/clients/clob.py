from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from polymarket_edge.clients.base import APIClient
from polymarket_edge.config import get_settings
from polymarket_edge.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class NormalizedOrderbook:
    token_id: str
    bids: list[dict[str, float]]
    asks: list[dict[str, float]]
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    spread: float | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_json: dict[str, Any] = field(default_factory=dict)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        levels.append({"price": price, "size": size})
    return sorted(levels, key=lambda row: row["price"], reverse=reverse)


class CLOBClient(APIClient):
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        super().__init__(base_url or settings.CLOB_API_BASE)

    async def get_orderbook(self, token_id: str) -> NormalizedOrderbook | None:
        data = await self.get_json("/book", {"token_id": token_id})
        if isinstance(data, dict):
            return self.normalize_orderbook(data, token_id=token_id)
        return None

    async def get_many_orderbooks(
        self,
        token_ids: list[str],
        concurrency: int = 10,
    ) -> dict[str, NormalizedOrderbook]:
        semaphore = asyncio.Semaphore(max(1, concurrency))
        results: dict[str, NormalizedOrderbook] = {}

        async def one(token_id: str) -> None:
            async with semaphore:
                try:
                    book = await self.get_orderbook(token_id)
                    if book is not None:
                        results[token_id] = book
                except Exception as exc:  # noqa: BLE001
                    log.warning("orderbook_fetch_failed", token_id=token_id, error=str(exc))

        await asyncio.gather(*(one(str(token_id)) for token_id in token_ids if token_id))
        return results

    def normalize_orderbook(self, raw: dict[str, Any], token_id: str | None = None) -> NormalizedOrderbook:
        tid = str(token_id or raw.get("asset_id") or raw.get("token_id") or raw.get("market") or "")
        bids = _levels(raw.get("bids") or raw.get("buy") or [], reverse=True)
        asks = _levels(raw.get("asks") or raw.get("sell") or [], reverse=False)
        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
        spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
        return NormalizedOrderbook(
            token_id=tid,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            mid=mid,
            spread=spread,
            raw_json=raw,
        )

