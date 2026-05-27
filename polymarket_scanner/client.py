"""Public Polymarket data clients.

The scanner deliberately stays read-only. It uses Gamma to discover markets and
optionally probes the CLOB top-of-book so alerts are ranked by executable ask
prices instead of only Polymarket's displayed/mid/last price.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from dateutil import parser as dtparser

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


@dataclass
class Market:
    id: str
    question: str
    slug: str
    end_date: datetime | None
    active: bool
    closed: bool
    accepting_orders: bool
    outcomes: list[str]
    prices: list[float | None]
    volume: float
    liquidity: float
    category: str | None
    event_title: str | None
    token_ids: list[str] = field(default_factory=list)
    description: str | None = None
    resolution_source: str | None = None
    rules: str | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def underdog_index(self) -> int | None:
        """Index of the cheapest positive outcome price, preserving outcome mapping."""
        candidates = [
            (i, p) for i, p in enumerate(self.prices)
            if p is not None and p > 0 and i < len(self.outcomes)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1])[0]

    @property
    def underdog_price(self) -> float | None:
        idx = self.underdog_index
        if idx is None:
            return None
        return self.prices[idx]

    @property
    def underdog_outcome(self) -> str | None:
        idx = self.underdog_index
        if idx is None or idx >= len(self.outcomes):
            return None
        return self.outcomes[idx]

    @property
    def underdog_token_id(self) -> str | None:
        idx = self.underdog_index
        if idx is None or idx >= len(self.token_ids):
            return None
        token_id = self.token_ids[idx]
        return token_id or None

    @property
    def has_clob_tokens(self) -> bool:
        return len([t for t in self.token_ids if t]) >= len(self.outcomes) >= 2

    @property
    def url(self) -> str:
        return f"https://polymarket.com/event/{self.slug}" if self.slug else ""

    @property
    def rule_text(self) -> str:
        parts = [self.question, self.event_title or "", self.category or ""]
        for key in ("description", "rules", "resolutionSource", "resolution_source"):
            val = self.raw.get(key)
            if val:
                parts.append(str(val))
        if self.description:
            parts.append(self.description)
        if self.rules:
            parts.append(self.rules)
        if self.resolution_source:
            parts.append(self.resolution_source)
        return "\n".join(parts)


@dataclass(frozen=True)
class TopOfBookQuote:
    token_id: str
    side: str
    price: float | None
    source: str


def _parse_list_field(raw: Any) -> list:
    """Gamma returns some list fields as JSON-encoded strings."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return []
    return []


def _parse_float_or_none(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _first_str(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        val = row.get(key)
        if val not in (None, ""):
            return str(val)
    return None


def _parse_market(row: dict[str, Any]) -> Market | None:
    try:
        outcomes = [str(o) for o in _parse_list_field(row.get("outcomes"))]
        prices_raw = _parse_list_field(row.get("outcomePrices"))
        # Preserve index mapping. Dropping blank prices shifts outcome/price pairs.
        prices = [_parse_float_or_none(p) for p in prices_raw]
        if len(prices) < len(outcomes):
            prices.extend([None] * (len(outcomes) - len(prices)))
        elif len(prices) > len(outcomes):
            prices = prices[:len(outcomes)]

        token_ids = [str(t) for t in _parse_list_field(row.get("clobTokenIds")) if t not in (None, "")]

        end_raw = row.get("endDate") or row.get("end_date_iso")
        end_date = dtparser.parse(end_raw) if end_raw else None
        if end_date and end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        events = row.get("events")
        event_title = None
        if isinstance(events, list) and events:
            event_title = events[0].get("title") or events[0].get("slug")

        return Market(
            id=str(row.get("id") or row.get("conditionId") or ""),
            question=row.get("question") or "",
            slug=row.get("slug") or "",
            end_date=end_date,
            active=bool(row.get("active")),
            closed=bool(row.get("closed")),
            accepting_orders=bool(row.get("acceptingOrders", True)),
            outcomes=outcomes,
            prices=prices,
            volume=float(row.get("volume24hr") or row.get("volume_24hr") or row.get("volume") or 0),
            liquidity=float(row.get("liquidity") or 0),
            category=row.get("category"),
            event_title=event_title,
            token_ids=token_ids,
            description=_first_str(row, "description"),
            resolution_source=_first_str(row, "resolutionSource", "resolution_source"),
            rules=_first_str(row, "rules"),
            raw=row,
        )
    except (KeyError, TypeError, ValueError) as exc:
        log.debug("skipping unparseable market row: %s", exc)
        return None


class PolymarketClient:
    def __init__(self, base_url: str = GAMMA_BASE, clob_url: str = CLOB_BASE, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.clob_url = clob_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polymarket-edge-scanner/0.2"})

    def iter_active_markets(
        self,
        page_size: int = 200,
        max_pages: int = 25,
        tag: str | None = None,
    ) -> Iterable[Market]:
        """Stream active, open, binary markets from Gamma."""
        params: dict[str, Any] = {
            "active": "true",
            "closed": "false",
            "limit": page_size,
            "order": "volume_24hr",
            "ascending": "false",
        }
        if tag:
            params["tag_slug"] = tag

        for page in range(max_pages):
            params["offset"] = page * page_size
            try:
                resp = self.session.get(
                    f"{self.base_url}/markets", params=params, timeout=self.timeout
                )
                resp.raise_for_status()
                rows = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("gamma /markets failed on page %d: %s", page, exc)
                time.sleep(2)
                return
            if not rows:
                return
            for row in rows:
                m = _parse_market(row)
                if m and m.active and not m.closed and len(m.outcomes) == 2 and len(m.prices) == 2:
                    yield m
            if len(rows) < page_size:
                return

    def get_best_prices_batch(self, token_ids: Iterable[str], side: str = "BUY") -> dict[str, TopOfBookQuote]:
        """Return best executable BUY/SELL price for token IDs.

        BUY is the best ask you would pay to buy shares. SELL is the best bid.
        The CLOB public API has changed shape before, so this method tries the
        documented batch endpoint and then falls back to per-token GET calls.
        """
        clean_ids = []
        seen = set()
        for token_id in token_ids:
            if token_id and token_id not in seen:
                clean_ids.append(str(token_id))
                seen.add(str(token_id))
        if not clean_ids:
            return {}

        side = side.upper()
        quotes: dict[str, TopOfBookQuote] = {}

        # Batch endpoint used by current SDK docs. Shape is intentionally kept
        # simple; if the API rejects it, the fallback below still works.
        payload = [{"token_id": token_id, "side": side} for token_id in clean_ids]
        try:
            resp = self.session.post(f"{self.clob_url}/prices", json=payload, timeout=self.timeout)
            if resp.ok:
                data = resp.json()
                # Observed/documented shapes include either {token: {BUY: "0.52"}}
                # or a list of per-token price objects. Accept both.
                if isinstance(data, dict):
                    for token_id, val in data.items():
                        price = None
                        if isinstance(val, dict):
                            price = _parse_float_or_none(val.get(side) or val.get(side.lower()) or val.get("price"))
                        else:
                            price = _parse_float_or_none(val)
                        quotes[str(token_id)] = TopOfBookQuote(str(token_id), side, price, "clob_batch")
                elif isinstance(data, list):
                    for row in data:
                        if not isinstance(row, dict):
                            continue
                        token_id = str(row.get("token_id") or row.get("asset_id") or row.get("market") or "")
                        if token_id:
                            quotes[token_id] = TopOfBookQuote(
                                token_id, side, _parse_float_or_none(row.get("price")), "clob_batch"
                            )
        except (requests.RequestException, ValueError) as exc:
            log.debug("clob batch price fetch failed: %s", exc)

        missing = [token_id for token_id in clean_ids if token_id not in quotes or quotes[token_id].price is None]
        for token_id in missing:
            try:
                resp = self.session.get(
                    f"{self.clob_url}/price",
                    params={"token_id": token_id, "side": side},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                price = None
                if isinstance(data, dict):
                    price = _parse_float_or_none(data.get("price") or data.get(side) or data.get(side.lower()))
                else:
                    price = _parse_float_or_none(data)
                quotes[token_id] = TopOfBookQuote(token_id, side, price, "clob_get")
            except (requests.RequestException, ValueError) as exc:
                log.debug("clob price fetch failed for %s: %s", token_id, exc)
                quotes.setdefault(token_id, TopOfBookQuote(token_id, side, None, "clob_unavailable"))
        return quotes
