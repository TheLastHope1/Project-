import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

import config
from strategy import Signal
from market_scanner import MarketInfo

logger = logging.getLogger("polymarket_bot.risk_manager")


@dataclass
class RiskDecision:
    """Result of a risk evaluation."""
    approved: bool
    position_size: float  # USDC amount to bet
    reason: str


class RiskManager:
    """
    Aggressive growth-oriented position sizing with profit compounding.

    Uses half-Kelly criterion and scales trade sizes with capital growth.
    No daily loss limits - trades 24/7. Profits are reinvested to compound
    account growth.
    """

    def __init__(self):
        self.current_capital = config.STARTING_CAPITAL
        self.peak_capital = config.STARTING_CAPITAL
        self.total_pnl = 0.0
        self.session_trades = 0
        self.session_wins = 0
        self.open_position_count = 0
        self.total_exposure = 0.0
        self._last_trade_time = 0.0
        # Tracks which (market_slug, window_end_ts) pairs we've already bet
        # on, so we never stack multiple bets on the same window.
        self._traded_windows: set[tuple[str, int]] = set()
        # Starting capital snapshot - set the first time we see a real
        # wallet balance so growth-% makes sense in live mode.
        self._live_starting_capital: Optional[float] = None

    def refresh_capital_from_wallet(self, wallet_balance: float) -> None:
        """
        Update capital from the live Polymarket USDC balance.

        wallet_balance is what's free in the wallet (excludes collateral
        locked in open positions). Total capital = wallet + open exposure.
        A negative value signals the fetch failed - we keep current_capital
        unchanged in that case.
        """
        if wallet_balance < 0:
            return  # fetch failed, stay with what we have

        total = wallet_balance + self.total_exposure

        # Record the first real balance we see as "starting capital" for
        # growth-% displays.
        if self._live_starting_capital is None:
            self._live_starting_capital = total
            logger.info(
                f"Live starting capital: ${total:.2f} "
                f"(wallet ${wallet_balance:.2f} + exposure ${self.total_exposure:.2f})"
            )

        self.current_capital = total
        if total > self.peak_capital:
            self.peak_capital = total

    @staticmethod
    def _window_key(market: MarketInfo) -> tuple[str, int]:
        return (market.slug, int(market.window_end.timestamp()))

    def has_traded_window(self, market: MarketInfo) -> bool:
        """True if we've already placed a bet on this exact 5-min window."""
        return self._window_key(market) in self._traded_windows

    def evaluate_trade(
        self,
        signal: Signal,
        market: Optional[MarketInfo] = None,
        current_time: float = 0,
    ) -> RiskDecision:
        """
        Evaluate whether a trade should be taken and how large it should be.

        Rejects trades when:
        - We've already bet on this market's current window
        - Too many concurrent positions open
        - Not enough capital for minimum bet
        - Edge below threshold
        """
        # Check 0: One bet per market per 5-min window
        if market is not None and self.has_traded_window(market):
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Already bet on this window ({market.slug})",
            )

        # Check 1: Max concurrent positions
        if self.open_position_count >= config.MAX_CONCURRENT_POSITIONS:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Max concurrent positions ({self.open_position_count})",
            )

        # Check 2: Minimum edge
        if signal.edge < config.MIN_EDGE_THRESHOLD:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Edge too small ({signal.edge:.1%})",
            )

        # Check 3: Enough capital for minimum bet
        available = self.current_capital - self.total_exposure
        if available < config.MIN_BET_SIZE:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Insufficient available capital (${available:.2f})",
            )

        # All checks passed - calculate position size with compounding
        size = self._calculate_position_size(signal)

        # Clamp to available capital (leave a small buffer for fees)
        size = min(size, available * 0.95)

        if size < config.MIN_BET_SIZE:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Calculated size too small (${size:.2f})",
            )

        return RiskDecision(
            approved=True,
            position_size=round(size, 2),
            reason=f"Approved: ${size:.2f} ({signal.bet_size_hint} confidence) | Capital: ${self.current_capital:.2f}",
        )

    def _calculate_position_size(self, signal: Signal) -> float:
        """
        Calculate position size using half-Kelly with compounding.

        As capital grows, trade sizes grow proportionally.
        Higher edge = larger bets. The account compounds naturally.
        """
        p = signal.confidence
        q = 1 - p

        # Calculate payout odds from market price
        token_price = signal.market_prob
        if token_price <= 0.01 or token_price >= 0.99:
            return config.MIN_BET_SIZE

        b = (1 - token_price) / token_price  # Odds

        # Kelly fraction
        kelly_f = (p * b - q) / b
        if kelly_f <= 0:
            return 0.0

        # Half Kelly for aggressive but not reckless sizing
        fraction = config.KELLY_FRACTION * kelly_f

        # Cap at max fraction of capital
        fraction = min(fraction, config.MAX_BET_FRACTION)

        # COMPOUND: Size scales with current capital, not starting capital
        size = fraction * self.current_capital

        # Dynamic max bet: scales with capital growth
        # At $150 max is $50, at $300 max is $100, at $1000 max is $333
        dynamic_max = max(config.MAX_BET_SIZE, self.current_capital * config.MAX_BET_FRACTION)
        size = min(size, dynamic_max)

        # Confidence-based scaling
        if signal.bet_size_hint == "high":
            # High confidence: full size
            pass
        elif signal.bet_size_hint == "medium":
            size *= 0.75
        else:
            # Low confidence: smaller but still meaningful
            size *= 0.50

        # Enforce minimum
        size = max(config.MIN_BET_SIZE, size)

        return size

    def record_trade_opened(
        self, cost_basis: float, market: Optional[MarketInfo] = None
    ):
        """Record that a new position was opened."""
        self.open_position_count += 1
        self.total_exposure += cost_basis
        self.session_trades += 1
        self._last_trade_time = time.time()

        if market is not None:
            self._traded_windows.add(self._window_key(market))
            self._prune_traded_windows()

        logger.info(
            f"Position opened: ${cost_basis:.2f} | "
            f"Open: {self.open_position_count} | "
            f"Exposure: ${self.total_exposure:.2f} | "
            f"Capital: ${self.current_capital:.2f}"
        )

    def _prune_traded_windows(self) -> None:
        """Drop window keys that are more than an hour past expiry."""
        cutoff = int(time.time()) - 3600
        self._traded_windows = {
            (slug, ts) for (slug, ts) in self._traded_windows if ts > cutoff
        }

    def record_trade_closed(self, cost_basis: float, pnl: float):
        """Record that a position was resolved and compound profits."""
        self.open_position_count = max(0, self.open_position_count - 1)
        self.total_exposure = max(0, self.total_exposure - cost_basis)
        self.current_capital += pnl
        self.total_pnl += pnl

        if pnl > 0:
            self.session_wins += 1

        # Track peak capital for reference
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        base = self._live_starting_capital or config.STARTING_CAPITAL
        growth = ((self.current_capital - base) / base) * 100 if base else 0.0

        logger.info(
            f"Position closed: PnL ${pnl:+.2f} | "
            f"Capital: ${self.current_capital:.2f} ({growth:+.1f}%) | "
            f"Peak: ${self.peak_capital:.2f} | "
            f"Total PnL: ${self.total_pnl:+.2f}"
        )

    def get_status(self) -> dict:
        """Return current state."""
        win_rate = (self.session_wins / self.session_trades * 100) if self.session_trades > 0 else 0
        base = self._live_starting_capital or config.STARTING_CAPITAL
        growth = ((self.current_capital - base) / base) * 100 if base else 0.0
        available = self.current_capital - self.total_exposure

        return {
            "capital": self.current_capital,
            "available": available,
            "peak_capital": self.peak_capital,
            "total_pnl": self.total_pnl,
            "growth_pct": growth,
            "session_trades": self.session_trades,
            "session_wins": self.session_wins,
            "win_rate": win_rate,
            "open_positions": self.open_position_count,
            "total_exposure": self.total_exposure,
            "next_trade_size": f"${min(config.MAX_BET_SIZE, self.current_capital * config.MAX_BET_FRACTION):.2f} max",
            "can_trade": (
                self.open_position_count < config.MAX_CONCURRENT_POSITIONS
                and available >= config.MIN_BET_SIZE
            ),
        }
