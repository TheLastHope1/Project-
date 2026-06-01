from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dateutil import parser as dtparser

from polymarket_edge.clients.base import APIClient
from polymarket_edge.config import get_settings


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=UTC)
        dt = dtparser.parse(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


class DataAPIClient(APIClient):
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        super().__init__(base_url or settings.DATA_API_BASE)

    async def get_trades(
        self,
        condition_id: str | None = None,
        market: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if condition_id:
            params["conditionId"] = condition_id
        if market:
            params["market"] = market
        data = await self.get_json("/trades", params)
        if isinstance(data, dict):
            data = data.get("data") or data.get("trades") or []
        return data if isinstance(data, list) else []

    def normalize_trade(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "proxy_wallet": raw.get("proxyWallet") or raw.get("proxy_wallet"),
            "side": raw.get("side"),
            "token_id": raw.get("asset") or raw.get("token_id") or raw.get("asset_id"),
            "condition_id": raw.get("conditionId") or raw.get("condition_id"),
            "size": _float_or_none(raw.get("size")),
            "price": _float_or_none(raw.get("price")),
            "timestamp": _parse_dt(raw.get("timestamp") or raw.get("createdAt") or raw.get("created_at")),
            "market_slug": raw.get("slug") or raw.get("marketSlug"),
            "outcome": raw.get("outcome"),
            "tx_hash": raw.get("transactionHash") or raw.get("tx_hash"),
            "raw_json": raw,
        }

