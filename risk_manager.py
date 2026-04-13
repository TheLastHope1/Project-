import logging
import math
from dataclasses import dataclass
from typing import Optional

import config
from strategy import Signal

logger = logging.getLogger("polymarket_bot.risk_manager")


@dataclass
class RiskDecision:
    """Result of a risk evaluation."""
    approved: bool
    position_size: float  # USDC amount to bet
    reason: str


class RiskManager:
    """
    Guards the bankroll with position sizing and risk limits.

    Uses quarter-Kelly criterion for sizing and enforces hard limits
    on daily losses, concurrent positions, and total exposure.
    """

    def __init__(self):
        self.current_capital = config.STARTING_CAPITAL
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.open_position_count = 0
        self.total_exposure = 0.0  # USDC locked in open positions
        self._last_trade_time = 0.0

    def evaluate_trade(self, signal: Signal, current_time: float = 0) -> RiskDecision:
        """
        Evaluate whether a trade should be taken and how large it should be.

        Runs through all risk checks in order. Any failure rejects the trade.
        """
        # Check 1: Daily loss limit
        if self.daily_pnl <= -config.MAX_DAILY_LOSS:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Daily loss limit hit (${self.daily_pnl:.2f})",
            )

        # Check 2: Daily trade limit
        if self.daily_trade_count >= config.DAILY_TRADE_LIMIT:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Daily trade limit reached ({self.daily_trade_count})",
            )

        # Check 3: Max concurrent positions
        if self.open_position_count >= config.MAX_CONCURRENT_POSITIONS:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Max concurrent positions ({self.open_position_count})",
            )

        # Check 4: Max total exposure
        remaining_exposure = config.MAX_TOTAL_EXPOSURE - self.total_exposure
        if remaining_exposure <= config.MIN_BET_SIZE:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Max exposure reached (${self.total_exposure:.2f})",
            )

        # Check 5: Minimum edge
        if signal.edge < config.MIN_EDGE_THRESHOLD:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Edge too small ({signal.edge:.1%})",
            )

        # Check 6: Capital floor (keep enough for at least 2 more bets)
        if self.current_capital < config.MIN_BET_SIZE * 2:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Capital too low (${self.current_capital:.2f})",
            )

        # Check 7: Cooldown
        import time
        now = current_time or time.time()
        if now - self._last_trade_time < config.COOLDOWN_SECONDS:
            elapsed = now - self._last_trade_time
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Cooldown active ({elapsed:.0f}s / {config.COOLDOWN_SECONDS}s)",
            )

        # All checks passed - calculate position size
        size = self._calculate_position_size(signal)

        # Clamp to remaining exposure
        size = min(size, remaining_exposure)

        # Clamp to available capital
        size = min(size, self.current_capital * 0.90)  # Keep 10% reserve

        if size < config.MIN_BET_SIZE:
            return RiskDecision(
                approved=False,
                position_size=0,
                reason=f"Calculated size too small (${size:.2f})",
            )

        return RiskDecision(
            approved=True,
            position_size=round(size, 2),
            reason=f"Approved: ${size:.2f} ({signal.bet_size_hint} confidence)",
        )

    def _calculate_position_size(self, signal: Signal) -> float:
        """
        Calculate position size using quarter-Kelly Criterion.

        Kelly formula for binary outcomes:
          f* = (p * b - q) / b
        where:
          p = probability of winning (our confidence)
          q = 1 - p
          b = payout odds = (1 - token_price) / token_price

        We use quarter-Kelly (0.25 * f*) for safety.
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
            return 0.0  # No edge according to Kelly

        # Quarter Kelly
        fraction = config.KELLY_FRACTION * kelly_f

        # Convert to dollar amount
        size = fraction * self.current_capital

        # Apply hard limits
        size = max(config.MIN_BET_SIZE, min(size, config.MAX_BET_SIZE))

        # Adjust by confidence tier
        if signal.bet_size_hint == "low":
            size = min(size, config.MIN_BET_SIZE + 5)  # $5-$10
        elif signal.bet_size_hint == "medium":
            size = min(size, 15.0)  # Up to $15
        # "high" gets the full calculated size

        return size

    def record_trade_opened(self, cost_basis: float):
        """Record that a new position was opened."""
        self.open_position_count += 1
        self.total_exposure += cost_basis
        self.daily_trade_count += 1
        import time
        self._last_trade_time = time.time()
        logger.info(
            f"Position opened: ${cost_basis:.2f} | "
            f"Open: {self.open_position_count} | "
            f"Exposure: ${self.total_exposure:.2f}"
        )

    def record_trade_closed(self, cost_basis: float, pnl: float):
        """Record that a position was resolved."""
        self.open_position_count = max(0, self.open_position_count - 1)
        self.total_exposure = max(0, self.total_exposure - cost_basis)
        self.current_capital += pnl
        self.daily_pnl += pnl
        logger.info(
            f"Position closed: PnL ${pnl:+.2f} | "
            f"Capital: ${self.current_capital:.2f} | "
            f"Daily PnL: ${self.daily_pnl:+.2f}"
        )

    def reset_daily(self):
        """Reset daily counters (call at midnight UTC)."""
        logger.info(
            f"Daily reset. Day ended with PnL: ${self.daily_pnl:+.2f}, "
            f"Trades: {self.daily_trade_count}"
        )
        self.daily_pnl = 0.0
        self.daily_trade_count = 0

    def get_status(self) -> dict:
        """Return current risk state."""
        return {
            "capital": self.current_capital,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trade_count,
            "open_positions": self.open_position_count,
            "total_exposure": self.total_exposure,
            "can_trade": (
                self.daily_pnl > -config.MAX_DAILY_LOSS
                and self.daily_trade_count < config.DAILY_TRADE_LIMIT
                and self.open_position_count < config.MAX_CONCURRENT_POSITIONS
                and self.current_capital >= config.MIN_BET_SIZE * 2
            ),
        }
