import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import requests
import config

logger = logging.getLogger("polymarket_bot.price_feed")


@dataclass
class PriceSnapshot:
    """Current BTC price data."""
    price: float
    bid: float
    ask: float
    timestamp: float


@dataclass
class CandleData:
    """A single candlestick."""
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float


@dataclass
class MomentumData:
    """Computed momentum indicators."""
    ema_fast: float
    ema_slow: float
    crossover: str
    price_vs_ema: float
    volatility: float
    trend_strength: float
    rsi: float
    momentum_5m: float
    momentum_15m: float


# Primary = Coinbase (geo-available in US). Secondary = Binance (fallback
# for regions where Coinbase is slow/blocked). Having two sources means
# one being down doesn't kill the bot.
COINBASE_TICKER_URL = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/bookTicker"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


class BinancePriceFeed:
    """BTC price feed. Tries Coinbase first, falls back to Binance.

    Name kept for backwards compatibility with existing imports.
    """

    def __init__(self):
        self._last_price = None
        self._last_candles = None
        self._candle_cache_time = 0

    # ── Current price ─────────────────────────────────────────────
    def get_current_price(self) -> Optional[PriceSnapshot]:
        snapshot = self._fetch_price_coinbase() or self._fetch_price_binance()
        if snapshot:
            self._last_price = snapshot
            return snapshot
        if self._last_price:
            logger.warning("Using cached price data.")
            return self._last_price
        return None

    def _fetch_price_coinbase(self) -> Optional[PriceSnapshot]:
        try:
            resp = requests.get(COINBASE_TICKER_URL, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            bid = float(data["bid"])
            ask = float(data["ask"])
            return PriceSnapshot(
                price=(bid + ask) / 2,
                bid=bid,
                ask=ask,
                timestamp=time.time(),
            )
        except Exception as e:
            logger.debug(f"Coinbase ticker fetch failed: {e}")
            return None

    def _fetch_price_binance(self) -> Optional[PriceSnapshot]:
        try:
            resp = requests.get(
                BINANCE_TICKER_URL, params={"symbol": "BTCUSDT"}, timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            bid = float(data["bidPrice"])
            ask = float(data["askPrice"])
            return PriceSnapshot(
                price=(bid + ask) / 2,
                bid=bid,
                ask=ask,
                timestamp=time.time(),
            )
        except Exception as e:
            logger.debug(f"Binance ticker fetch failed: {e}")
            return None

    # ── Recent candles ────────────────────────────────────────────
    def get_recent_candles(self, interval: str = "1m",
                           limit: int = 30) -> list[CandleData]:
        """Fetch recent 1-minute candles. Coinbase first, Binance fallback."""
        if self._last_candles and (time.time() - self._candle_cache_time < 10):
            return self._last_candles

        candles = (
            self._fetch_candles_coinbase(limit)
            or self._fetch_candles_binance(interval, limit)
        )
        if candles:
            self._last_candles = candles
            self._candle_cache_time = time.time()
            return candles

        return self._last_candles or []

    def _fetch_candles_coinbase(self, limit: int) -> Optional[list[CandleData]]:
        try:
            # Coinbase returns up to 300 candles. granularity=60 = 1-minute.
            params = {"granularity": 60}
            resp = requests.get(COINBASE_CANDLES_URL, params=params, timeout=10)
            resp.raise_for_status()
            raw = resp.json()
            # Coinbase format: [[ts, low, high, open, close, volume], ...]
            # Sorted descending (newest first). We want ascending.
            raw.sort(key=lambda x: x[0])
            raw = raw[-limit:]
            return [
                CandleData(
                    open=float(k[3]),
                    high=float(k[2]),
                    low=float(k[1]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    timestamp=float(k[0]),
                )
                for k in raw
            ]
        except Exception as e:
            logger.debug(f"Coinbase candles fetch failed: {e}")
            return None

    def _fetch_candles_binance(self, interval: str, limit: int) -> Optional[list[CandleData]]:
        try:
            params = {"symbol": "BTCUSDT", "interval": interval, "limit": limit}
            resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=5)
            resp.raise_for_status()
            raw = resp.json()
            return [
                CandleData(
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    timestamp=float(k[0]) / 1000,
                )
                for k in raw
            ]
        except Exception as e:
            logger.debug(f"Binance klines fetch failed: {e}")
            return None

    # ── Momentum computation ──────────────────────────────────────
    def compute_momentum(self, candles: list[CandleData]) -> Optional[MomentumData]:
        if len(candles) < config.EMA_SLOW_PERIOD + 1:
            logger.warning(f"Not enough candles ({len(candles)}) for momentum calc.")
            return None

        closes = np.array([c.close for c in candles])
        ema_fast = self._compute_ema(closes, config.EMA_FAST_PERIOD)
        ema_slow = self._compute_ema(closes, config.EMA_SLOW_PERIOD)

        current_fast = ema_fast[-1]
        current_slow = ema_slow[-1]

        if len(ema_fast) >= 2 and len(ema_slow) >= 2:
            prev_diff = ema_fast[-2] - ema_slow[-2]
            curr_diff = current_fast - current_slow
            if prev_diff <= 0 and curr_diff > 0:
                crossover = "bullish"
            elif prev_diff >= 0 and curr_diff < 0:
                crossover = "bearish"
            else:
                crossover = "bullish" if curr_diff > 0 else "bearish"
        else:
            crossover = "neutral"

        current_price = closes[-1]
        price_vs_ema = (current_price - current_fast) / current_fast
        returns = np.diff(closes) / closes[:-1]
        volatility = float(np.std(returns)) if len(returns) > 1 else 0.0
        trend_strength = abs(current_fast - current_slow) / current_slow
        rsi = self._compute_rsi(closes, 14)
        momentum_5m = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 else 0.0
        momentum_15m = (closes[-1] - closes[-16]) / closes[-16] if len(closes) >= 16 else 0.0

        return MomentumData(
            ema_fast=current_fast,
            ema_slow=current_slow,
            crossover=crossover,
            price_vs_ema=price_vs_ema,
            volatility=volatility,
            trend_strength=trend_strength,
            rsi=rsi,
            momentum_5m=momentum_5m,
            momentum_15m=momentum_15m,
        )

    def _compute_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        alpha = 2.0 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _compute_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
