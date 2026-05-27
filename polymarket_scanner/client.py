"""Public Polymarket data clients.

The scanner deliberately stays read-only. Gamma is used for market/event
discovery; the CLOB exposes the executable book, per-token fee rate, and
tick size that the scanner relies on to compute honest expected value.

``/book`` is the canonical executable-price source. ``/price`` is kept as a
fallback because it's cheaper, but every ranked alert should ideally carry a
``/book`` snapshot so depth, spread, and tick are recorded with the trade
journal.
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

from .fees import depth_weighted_ask

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


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    """A normalised CLOB order-book snapshot.

    ``bids`` are sorted high to low, ``asks`` low to high. ``tick_size`` and
    ``min_order_size`` are from the same payload when the API includes them.
    """

    token_id: str
    bids: list[BookLevel]
    asks: list[BookLevel]
    tick_size: float | None = None
    min_order_size: float | None = None
    neg_risk: bool | None = None
    last_trade_price: float | None = None
    timestamp: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> float | None:
        b, a = self.best_bid, self.best_ask
        if b is None or a is None:
            return None
        return round(a - b, 6)

    @property
    def midpoint(self) -> float | None:
        b, a = self.best_bid, self.best_ask
        if b is None or a is None:
            return None
        return round((a + b) / 2.0, 6)

    @property
    def ask_depth_usd(self) -> float:
        return sum(l.price * l.size for l in self.asks)

    def vwap_ask(self, target_shares: float) -> tuple[float, float]:
        """Depth-weighted average ask price to fill ``target_shares``.

        Returns ``(vwap, shares_filled)``. ``shares_filled < target_shares``
        means the visible book is thinner than the requested size.
        """
        return depth_weighted_ask([(l.price, l.size) for l in self.asks], target_shares)


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
        self.session.headers.update({"User-Agent": "polymarket-edge-scanner/0.3"})
        # Tiny in-process caches: fee-rate and tick-size rarely change per token
        # in a single scan cycle. Capped to avoid unbounded growth in long runs.
        self._fee_rate_cache: dict[str, float] = {}
        self._tick_size_cache: dict[str, float] = {}

    def iter_active_markets(
        self,
        page_size: int = 200,
        max_pages: int = 25,
        tag: str | None = None,
    ) -> Iterable[Market]:
        """Stream active, open, binary markets from Gamma.

        Kept for back-compat with the legacy scan loop. New code should prefer
        ``iter_active_events_keyset`` which is more stable under live market
        churn and matches Polymarket's recommended discovery path.
        """
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

    def iter_active_events_keyset(
        self,
        page_size: int = 200,
        max_pages: int = 25,
        tag: str | None = None,
    ) -> Iterable[Market]:
        """Discover active markets via Gamma's keyset event pagination.

        This is the path Polymarket's docs recommend for active discovery:
        cursors are stable under live churn (new events, closed events) in a
        way that ``offset`` pagination on ``/markets`` is not. Yields the same
        ``Market`` objects as ``iter_active_markets``.

        Falls back to ``iter_active_markets`` if the keyset endpoint returns
        an unexpected shape -- this keeps the scanner running on a temporary
        API regression without manual intervention.
        """
        cursor: str | None = None
        seen_market_ids: set[str] = set()
        for page in range(max_pages):
            params: dict[str, Any] = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
            }
            if tag:
                params["tag_slug"] = tag
            if cursor:
                params["after_cursor"] = cursor
            try:
                resp = self.session.get(
                    f"{self.base_url}/events/keyset", params=params, timeout=self.timeout
                )
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("gamma /events/keyset failed on page %d: %s -- falling back to /markets", page, exc)
                # Yield what we already produced, then defer to the legacy path.
                yield from self.iter_active_markets(
                    page_size=page_size, max_pages=max_pages, tag=tag
                )
                return

            # Accept both wrapped {"data": [...], "next_cursor": "..."} and
            # bare list responses (Gamma has shipped both shapes).
            if isinstance(payload, dict):
                events = payload.get("data") or payload.get("events") or []
                cursor = payload.get("next_cursor") or payload.get("nextCursor")
            elif isinstance(payload, list):
                events = payload
                cursor = None
            else:
                log.warning("gamma /events/keyset returned unexpected shape: %s", type(payload).__name__)
                return

            if not events:
                return

            for event in events:
                markets = event.get("markets") if isinstance(event, dict) else None
                if not isinstance(markets, list):
                    continue
                event_title = event.get("title") or event.get("slug")
                for row in markets:
                    if not isinstance(row, dict):
                        continue
                    # Inject the event title so downstream classification can use it.
                    row.setdefault("events", [{"title": event_title}])
                    m = _parse_market(row)
                    if not m:
                        continue
                    if m.id in seen_market_ids:
                        continue
                    if not (m.active and not m.closed and len(m.outcomes) == 2 and len(m.prices) == 2):
                        continue
                    seen_market_ids.add(m.id)
                    yield m

            if not cursor:
                return

    def get_best_prices_batch(self, token_ids: Iterable[str], side: str = "BUY") -> dict[str, TopOfBookQuote]:
        """Return CLOB price endpoint quotes for token IDs.

        Polymarket's price endpoint returns the best bid for BUY side and the
        best ask for SELL side. The CLOB public API has changed shape before, so
        this method tries the documented batch endpoint and then falls back to
        per-token GET calls.
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

    # ---- CLOB /book ------------------------------------------------------

    def get_book(self, token_id: str) -> OrderBook | None:
        """Fetch the full order book for one token via ``GET /book``.

        Returns ``None`` on transport error. An empty book (both sides empty)
        is still returned so callers can distinguish "no orders" from "no
        response".
        """
        if not token_id:
            return None
        try:
            resp = self.session.get(
                f"{self.clob_url}/book",
                params={"token_id": str(token_id)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.debug("clob /book fetch failed for %s: %s", token_id, exc)
            return None
        return _parse_book(str(token_id), data) if isinstance(data, dict) else None

    def get_books_batch(self, token_ids: Iterable[str]) -> dict[str, OrderBook]:
        """Fetch order books for many tokens.

        Tries the batch ``POST /books`` endpoint first, then falls back to
        per-token ``GET /book`` for any token the batch didn't return. This
        mirrors how ``get_best_prices_batch`` degrades.
        """
        clean_ids: list[str] = []
        seen: set[str] = set()
        for tid in token_ids:
            if tid and tid not in seen:
                clean_ids.append(str(tid))
                seen.add(str(tid))
        if not clean_ids:
            return {}

        books: dict[str, OrderBook] = {}
        payload = [{"token_id": tid} for tid in clean_ids]
        try:
            resp = self.session.post(
                f"{self.clob_url}/books", json=payload, timeout=self.timeout
            )
            if resp.ok:
                data = resp.json()
                # Observed shapes: list of book objects, or {token_id: book}.
                if isinstance(data, list):
                    for row in data:
                        if not isinstance(row, dict):
                            continue
                        tid = str(row.get("asset_id") or row.get("token_id") or row.get("market") or "")
                        if tid:
                            books[tid] = _parse_book(tid, row)
                elif isinstance(data, dict):
                    for tid, row in data.items():
                        if isinstance(row, dict):
                            books[str(tid)] = _parse_book(str(tid), row)
        except (requests.RequestException, ValueError) as exc:
            log.debug("clob /books batch fetch failed: %s", exc)

        for tid in clean_ids:
            if tid in books:
                continue
            book = self.get_book(tid)
            if book is not None:
                books[tid] = book
        return books

    # ---- CLOB /fee-rate, /tick-size --------------------------------------

    def get_fee_rate(self, token_id: str) -> float | None:
        """Fetch the per-token taker fee rate via ``GET /fee-rate``.

        Cached in process for the lifetime of this client. Returns ``None``
        if the endpoint is unreachable or returns a non-numeric value; the
        caller should then fall back to ``fees.category_fee_rate``.
        """
        if not token_id:
            return None
        cached = self._fee_rate_cache.get(token_id)
        if cached is not None:
            return cached
        try:
            resp = self.session.get(
                f"{self.clob_url}/fee-rate",
                params={"token_id": str(token_id)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.debug("clob /fee-rate fetch failed for %s: %s", token_id, exc)
            return None
        if isinstance(data, dict):
            rate = _parse_float_or_none(
                data.get("base_fee") or data.get("fee_rate") or data.get("rate")
            )
        else:
            rate = _parse_float_or_none(data)
        if rate is None:
            return None
        # Polymarket has shipped fee rates as either decimal (0.03) or bps (300).
        # Normalise: anything > 1 is treated as bps.
        if rate > 1.0:
            rate = rate / 10_000.0
        # Cap cache size to avoid unbounded growth on long-running scanners.
        if len(self._fee_rate_cache) > 4096:
            self._fee_rate_cache.clear()
        self._fee_rate_cache[token_id] = rate
        return rate

    def get_tick_size(self, token_id: str) -> float | None:
        """Fetch the per-token minimum tick size via ``GET /tick-size``."""
        if not token_id:
            return None
        cached = self._tick_size_cache.get(token_id)
        if cached is not None:
            return cached
        try:
            resp = self.session.get(
                f"{self.clob_url}/tick-size",
                params={"token_id": str(token_id)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.debug("clob /tick-size fetch failed for %s: %s", token_id, exc)
            return None
        if isinstance(data, dict):
            tick = _parse_float_or_none(
                data.get("minimum_tick_size") or data.get("tick_size")
            )
        else:
            tick = _parse_float_or_none(data)
        if tick is None or tick <= 0:
            return None
        if len(self._tick_size_cache) > 4096:
            self._tick_size_cache.clear()
        self._tick_size_cache[token_id] = tick
        return tick

    # ---- Side-semantics contract check -----------------------------------

    def validate_price_side_semantics(self, token_id: str) -> dict[str, Any]:
        """Compare ``/price`` BUY/SELL responses against ``/book`` for the
        same token. The PDF review flagged ``/price`` side wording as the
        single most error-prone integration point in this codebase, so this
        helper makes the assumption testable.

        Expected:
            - ``/price?side=BUY``  ≈ best_bid (highest bid from /book)
            - ``/price?side=SELL`` ≈ best_ask (lowest ask from /book)

        Returns a dict with both sources, the deltas, and an ``ok`` flag.
        Caller decides whether to raise/halt -- this method never raises.
        """
        result: dict[str, Any] = {
            "token_id": token_id,
            "ok": False,
            "buy_price": None,
            "sell_price": None,
            "best_bid": None,
            "best_ask": None,
            "buy_minus_bid": None,
            "sell_minus_ask": None,
            "notes": [],
        }
        book = self.get_book(token_id)
        if book is None:
            result["notes"].append("book_unavailable")
            return result
        result["best_bid"] = book.best_bid
        result["best_ask"] = book.best_ask

        buy = self.get_best_prices_batch([token_id], side="BUY").get(token_id)
        sell = self.get_best_prices_batch([token_id], side="SELL").get(token_id)
        result["buy_price"] = buy.price if buy else None
        result["sell_price"] = sell.price if sell else None

        if book.best_bid is not None and result["buy_price"] is not None:
            result["buy_minus_bid"] = round(result["buy_price"] - book.best_bid, 6)
        if book.best_ask is not None and result["sell_price"] is not None:
            result["sell_minus_ask"] = round(result["sell_price"] - book.best_ask, 6)

        # Allow one tick of slack to absorb non-atomic timing between calls.
        tick = self.get_tick_size(token_id) or 0.01
        bid_ok = (
            result["buy_minus_bid"] is not None
            and abs(result["buy_minus_bid"]) <= tick
        )
        ask_ok = (
            result["sell_minus_ask"] is not None
            and abs(result["sell_minus_ask"]) <= tick
        )
        result["ok"] = bool(bid_ok and ask_ok)
        if not bid_ok:
            result["notes"].append("buy_side_disagrees_with_best_bid")
        if not ask_ok:
            result["notes"].append("sell_side_disagrees_with_best_ask")
        return result


def _parse_book_level(row: Any) -> BookLevel | None:
    if not isinstance(row, dict):
        return None
    price = _parse_float_or_none(row.get("price"))
    size = _parse_float_or_none(row.get("size") or row.get("quantity"))
    if price is None or size is None or size <= 0:
        return None
    return BookLevel(price=price, size=size)


def _parse_book(token_id: str, data: dict[str, Any]) -> OrderBook:
    raw_bids = data.get("bids") or []
    raw_asks = data.get("asks") or []
    bids = [b for b in (_parse_book_level(r) for r in raw_bids) if b is not None]
    asks = [a for a in (_parse_book_level(r) for r in raw_asks) if a is not None]
    # Defensive ordering: highest bid first, lowest ask first.
    bids.sort(key=lambda b: b.price, reverse=True)
    asks.sort(key=lambda a: a.price)

    ts_raw = data.get("timestamp") or data.get("ts")
    ts: datetime | None = None
    if ts_raw is not None:
        try:
            ts_int = int(ts_raw)
            # Heuristic: > 1e12 = milliseconds, else seconds.
            if ts_int > 1_000_000_000_000:
                ts = datetime.fromtimestamp(ts_int / 1000.0, tz=timezone.utc)
            else:
                ts = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        except (TypeError, ValueError):
            try:
                ts = dtparser.parse(str(ts_raw))
            except (ValueError, TypeError):
                ts = None

    return OrderBook(
        token_id=token_id,
        bids=bids,
        asks=asks,
        tick_size=_parse_float_or_none(data.get("tick_size") or data.get("minimum_tick_size")),
        min_order_size=_parse_float_or_none(data.get("min_order_size") or data.get("minimum_order_size")),
        neg_risk=bool(data.get("neg_risk")) if "neg_risk" in data else None,
        last_trade_price=_parse_float_or_none(data.get("last_trade_price")),
        timestamp=ts,
        raw=data,
    )
