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
    crossover: str  # "bullish", "bearish", "neutral"
    price_vs_ema: float  # % distance from fast EMA
    volatility: float  # std dev of recent returns
    trend_strength: float  # abs(fast - slow) / slow
    rsi: float  # 14-period RSI
    momentum_5m: float  # 5-min price change %
    momentum_15m: float  # 15-min price change %


class BinancePriceFeed:
    """Real-time BTC price data from Binance public API."""

    SYMBOL = "BTCUSDT"

    def __init__(self):
        self._last_price = None
        self._last_candles = None
        self._candle_cache_time = 0

    def get_current_price(self) -> Optional[PriceSnapshot]:
        """Fetch current BTC/USDT bid/ask from Binance."""
        url = f"{config.BINANCE_API_URL}/api/v3/ticker/bookTicker"
        params = {"symbol": self.SYMBOL}

        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=5)
                resp.raise_for_status()
                data = resp.json()

                bid = float(data["bidPrice"])
                ask = float(data["askPrice"])
                mid = (bid + ask) / 2

                snapshot = PriceSnapshot(
                    price=mid,
                    bid=bid,
                    ask=ask,
                    timestamp=time.time(),
                )
                self._last_price = snapshot
                return snapshot

            except Exception as e:
                logger.warning(f"Price fetch attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(1)

        # Return cached price if available
        if self._last_price:
            logger.warning("Using cached price data.")
            return self._last_price
        return None

    def get_recent_candles(self, interval: str = "1m",
                           limit: int = 30) -> list[CandleData]:
        """Fetch recent 1-minute candles from Binance."""
        # Use cache if fresh (< 10 seconds old)
        if self._last_candles and (time.time() - self._candle_cache_time < 10):
            return self._last_candles

        url = f"{config.BINANCE_API_URL}/api/v3/klines"
        params = {
            "symbol": self.SYMBOL,
            "interval": interval,
            "limit": limit,
        }

        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                candles = []
                for k in data:
                    candles.append(CandleData(
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        volume=float(k[5]),
                        timestamp=float(k[0]) / 1000,  # ms to seconds
                    ))

                self._last_candles = candles
                self._candle_cache_time = time.time()
                return candles

            except Exception as e:
                logger.warning(f"Candle fetch attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(1)

        return self._last_candles or []

    def compute_momentum(self, candles: list[CandleData]) -> Optional[MomentumData]:
        """Calculate momentum indicators from candle data."""
        if len(candles) < config.EMA_SLOW_PERIOD + 1:
            logger.warning(f"Not enough candles ({len(candles)}) for momentum calc.")
            return None

        closes = np.array([c.close for c in candles])

        # EMAs
        ema_fast = self._compute_ema(closes, config.EMA_FAST_PERIOD)
        ema_slow = self._compute_ema(closes, config.EMA_SLOW_PERIOD)

        current_fast = ema_fast[-1]
        current_slow = ema_slow[-1]

        # Crossover detection
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

        # Price vs EMA
        current_price = closes[-1]
        price_vs_ema = (current_price - current_fast) / current_fast

        # Volatility (std dev of 1-minute returns)
        returns = np.diff(closes) / closes[:-1]
        volatility = float(np.std(returns)) if len(returns) > 1 else 0.0

        # Trend strength
        trend_strength = abs(current_fast - current_slow) / current_slow

        # RSI (14-period)
        rsi = self._compute_rsi(closes, 14)

        # Momentum (price change over N candles)
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
        """Compute Exponential Moving Average."""
        alpha = 2.0 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _compute_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        """Compute RSI (Relative Strength Index)."""
        if len(closes) < period + 1:
            return 50.0  # neutral default

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
