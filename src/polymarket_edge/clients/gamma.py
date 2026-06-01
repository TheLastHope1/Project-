from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from polymarket_edge.clients.base import APIClient
from polymarket_edge.config import get_settings


class GammaClient(APIClient):
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        super().__init__(base_url or settings.GAMMA_API_BASE)

    async def list_events(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        data = await self.get_json(
            "/events",
            {
                "active": str(active).lower(),
                "closed": str(closed).lower(),
                "limit": limit,
                "offset": offset,
            },
        )
        return data if isinstance(data, list) else []

    async def iter_active_events(self, max_events: int | None = None) -> AsyncIterator[dict[str, Any]]:
        fetched = 0
        offset = 0
        limit = 100
        while max_events is None or fetched < max_events:
            batch = await self.list_events(limit=min(limit, (max_events or limit) - fetched), offset=offset)
            if not batch:
                return
            for row in batch:
                fetched += 1
                yield row
                if max_events is not None and fetched >= max_events:
                    return
            offset += len(batch)
            if len(batch) < limit:
                return

    async def list_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        data = await self.get_json(
            "/markets",
            {
                "active": str(active).lower(),
                "closed": str(closed).lower(),
                "limit": limit,
                "offset": offset,
                "order": "volume_24hr",
                "ascending": "false",
            },
        )
        return data if isinstance(data, list) else []

    async def iter_active_markets(self, max_markets: int | None = None) -> AsyncIterator[dict[str, Any]]:
        fetched = 0
        offset = 0
        limit = 100
        while max_markets is None or fetched < max_markets:
            batch = await self.list_markets(limit=min(limit, (max_markets or limit) - fetched), offset=offset)
            if not batch:
                return
            for row in batch:
                fetched += 1
                yield row
                if max_markets is not None and fetched >= max_markets:
                    return
            offset += len(batch)
            if len(batch) < limit:
                return

