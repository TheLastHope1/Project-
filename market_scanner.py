import logging
import re
import time
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import requests
import config

logger = logging.getLogger("polymarket_bot.market_scanner")


@dataclass
class MarketInfo:
    """Represents a tradeable BTC 5-minute market."""
    slug: str
    condition_id: str
    yes_token_id: str
    no_token_id: str
    question: str
    strike_price: float
    window_start: datetime
    window_end: datetime
    market_id: str

    @property
    def seconds_until_close(self) -> float:
        now = datetime.now(timezone.utc)
        return max(0, (self.window_end - now).total_seconds())


class MarketScanner:
    """Discovers and filters active BTC 5-minute markets on Polymarket."""

    INTERVAL_SECONDS = 300  # 5-minute windows
    SLUG_PREFIX = "will-btc"

    def __init__(self):
        self._cache = {}
        self._cache_ttl = 30  # seconds

    def get_current_window_timestamp(self) -> int:
        """Calculate the current 5-minute window start timestamp."""
        now = int(time.time())
        return now - (now % self.INTERVAL_SECONDS)

    def get_next_window_timestamp(self) -> int:
        """Get the next 5-minute window start timestamp."""
        return self.get_current_window_timestamp() + self.INTERVAL_SECONDS

    def seconds_until_window_close(self) -> float:
        """Seconds remaining in the current 5-minute window."""
        now = time.time()
        window_start = now - (now % self.INTERVAL_SECONDS)
        window_end = window_start + self.INTERVAL_SECONDS
        return max(0, window_end - now)

    def find_active_btc_5min_markets(self) -> list[MarketInfo]:
        """
        Search for active Bitcoin 5-minute markets on Polymarket.
        Uses the Gamma API to find markets matching BTC 5-min criteria.
        """
        markets = []

        # Try multiple search approaches
        search_queries = [
            {"tag": "btc-5-minute", "active": "true", "closed": "false"},
            {"slug_contains": "btc-updown-5m", "active": "true", "closed": "false"},
        ]

        # Also try the deterministic slug approach
        current_ts = self.get_current_window_timestamp()
        next_ts = self.get_next_window_timestamp()

        for ts in [current_ts, next_ts]:
            slug = f"btc-updown-5m-{ts}"
            market = self._fetch_market_by_slug(slug)
            if market:
                markets.append(market)

        # If deterministic approach didn't work, search by keywords
        if not markets:
            markets = self._search_markets_by_keyword()

        return markets

    def _fetch_market_by_slug(self, slug: str) -> Optional[MarketInfo]:
        """Fetch a specific market by its slug from the Gamma API."""
        cache_key = f"slug:{slug}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{config.GAMMA_API_URL}/markets"
        params = {"slug": slug}

        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    return None

                # Gamma API returns a list
                market_data = data[0] if isinstance(data, list) else data
                market = self._parse_market(market_data)
                self._set_cached(cache_key, market)
                return market

            except requests.RequestException as e:
                logger.warning(f"Fetch slug '{slug}' attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse market data for slug '{slug}': {e}")
                return None

        return None

    def _search_markets_by_keyword(self) -> list[MarketInfo]:
        """Search for BTC 5-min markets using keyword queries."""
        url = f"{config.GAMMA_API_URL}/markets"
        keywords = ["Bitcoin 5 minute", "BTC 5 minute", "BTC 5-minute"]
        markets = []
        seen_ids = set()

        for keyword in keywords:
            params = {
                "search": keyword,
                "active": "true",
                "closed": "false",
                "limit": 10,
            }

            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                if not data:
                    continue

                items = data if isinstance(data, list) else [data]
                for item in items:
                    market = self._parse_market(item)
                    if market and market.condition_id not in seen_ids:
                        if self._is_btc_5min_market(market):
                            markets.append(market)
                            seen_ids.add(market.condition_id)

            except Exception as e:
                logger.warning(f"Keyword search '{keyword}' failed: {e}")

        return markets

    def _parse_market(self, data: dict) -> Optional[MarketInfo]:
        """Parse raw market JSON into a MarketInfo object."""
        try:
            # Extract token IDs from clobTokenIds
            clob_token_ids = data.get("clobTokenIds", "[]")
            if isinstance(clob_token_ids, str):
                token_ids = json.loads(clob_token_ids)
            else:
                token_ids = clob_token_ids

            if len(token_ids) < 2:
                return None

            question = data.get("question", "")
            strike_price = self._parse_strike_price(question)

            # Parse timestamps
            end_date_str = data.get("endDate", "")
            if end_date_str:
                window_end = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
            else:
                # Estimate from current window
                ts = self.get_current_window_timestamp() + self.INTERVAL_SECONDS
                window_end = datetime.fromtimestamp(ts, tz=timezone.utc)

            window_start = datetime.fromtimestamp(
                window_end.timestamp() - self.INTERVAL_SECONDS, tz=timezone.utc
            )

            return MarketInfo(
                slug=data.get("slug", ""),
                condition_id=data.get("conditionId", data.get("condition_id", "")),
                yes_token_id=token_ids[0],
                no_token_id=token_ids[1],
                question=question,
                strike_price=strike_price,
                window_start=window_start,
                window_end=window_end,
                market_id=data.get("id", ""),
            )
        except Exception as e:
            logger.error(f"Failed to parse market: {e}")
            return None

    def _parse_strike_price(self, question: str) -> float:
        """Extract the BTC strike price from the market question."""
        # Match patterns like $84,500 or $84,500.00 or $84500
        patterns = [
            r'\$([0-9,]+\.?\d*)',
            r'above\s+([0-9,]+\.?\d*)',
            r'below\s+([0-9,]+\.?\d*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(",", "")
                try:
                    return float(price_str)
                except ValueError:
                    continue
        return 0.0

    def _is_btc_5min_market(self, market: MarketInfo) -> bool:
        """Check if a market is a valid BTC 5-minute binary market."""
        q = market.question.lower()
        has_btc = "btc" in q or "bitcoin" in q
        has_timeframe = "5 min" in q or "5-min" in q or "five min" in q
        has_price = market.strike_price > 0
        return has_btc and has_timeframe and has_price

    def _get_cached(self, key: str):
        """Get a value from cache if not expired."""
        if key in self._cache:
            value, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return value
            del self._cache[key]
        return None

    def _set_cached(self, key: str, value):
        """Store a value in cache."""
        self._cache[key] = (value, time.time())
