"""Minimal Polymarket Gamma API client.

Gamma is Polymarket's public read-only catalog API. No auth required to list
markets and read prices. We only need read access since the scanner just
surfaces opportunities - the user places trades manually.
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
    prices: list[float]
    volume: float
    liquidity: float
    category: str | None
    event_title: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def underdog_price(self) -> float | None:
        """Price of the cheapest outcome (implied probability of underdog)."""
        valid = [p for p in self.prices if p and p > 0]
        return min(valid) if valid else None

    @property
    def underdog_outcome(self) -> str | None:
        if not self.prices or not self.outcomes:
            return None
        idx = min(range(len(self.prices)), key=lambda i: self.prices[i] or 1.0)
        return self.outcomes[idx]

    @property
    def url(self) -> str:
        return f"https://polymarket.com/event/{self.slug}" if self.slug else ""


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


def _parse_market(row: dict[str, Any]) -> Market | None:
    try:
        outcomes = _parse_list_field(row.get("outcomes"))
        prices_raw = _parse_list_field(row.get("outcomePrices"))
        prices = [float(p) for p in prices_raw if p not in (None, "")]
        end_raw = row.get("endDate") or row.get("end_date_iso")
        end_date = dtparser.parse(end_raw) if end_raw else None
        if end_date and end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        return Market(
            id=str(row.get("id") or row.get("conditionId") or ""),
            question=row.get("question") or "",
            slug=row.get("slug") or "",
            end_date=end_date,
            active=bool(row.get("active")),
            closed=bool(row.get("closed")),
            accepting_orders=bool(row.get("acceptingOrders", True)),
            outcomes=[str(o) for o in outcomes],
            prices=prices,
            volume=float(row.get("volume") or 0),
            liquidity=float(row.get("liquidity") or 0),
            category=row.get("category"),
            event_title=(row.get("events") or [{}])[0].get("title")
                if isinstance(row.get("events"), list) and row.get("events") else None,
            raw=row,
        )
    except (KeyError, TypeError, ValueError) as exc:
        log.debug("skipping unparseable market row: %s", exc)
        return None


class PolymarketClient:
    def __init__(self, base_url: str = GAMMA_BASE, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polymarket-forfeit-scanner/0.1"})

    def iter_active_markets(
        self,
        page_size: int = 200,
        max_pages: int = 25,
        tag: str | None = None,
    ) -> Iterable[Market]:
        """Stream active, open, binary markets."""
        params: dict[str, Any] = {
            "active": "true",
            "closed": "false",
            "limit": page_size,
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
                if m and m.active and not m.closed and len(m.prices) == 2:
                    yield m
            if len(rows) < page_size:
                return
