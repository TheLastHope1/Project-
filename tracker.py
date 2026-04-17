import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import config
from market_scanner import MarketInfo
from strategy import Signal
from executor import OrderResult

logger = logging.getLogger("polymarket_bot.tracker")


@dataclass
class Position:
    """An open or resolved trading position."""
    market_slug: str
    token_id: str
    direction: str           # "YES" or "NO"
    entry_price: float       # Avg price per share
    cost_basis: float        # Total USDC spent
    order_id: str
    entry_time: float        # Unix timestamp
    window_end: float        # When the market resolves
    status: str = "OPEN"     # "OPEN", "WON", "LOST"
    pnl: float = 0.0
    exit_time: Optional[float] = None


@dataclass
class TradeRecord:
    """A complete trade record for logging."""
    timestamp: str
    market_slug: str
    question: str
    direction: str
    edge: float
    confidence: float
    market_prob: float
    bet_size: float
    order_id: str
    outcome: str  # "WIN", "LOSS", "PENDING"
    pnl: float
    capital_after: float
    reasoning: str


class TradeTracker:
    """Tracks positions, P&L, and trade history."""

    def __init__(self):
        self.positions: list[Position] = []
        self.trade_history: list[TradeRecord] = []
        self.total_pnl = 0.0
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def open_position(
        self,
        market: MarketInfo,
        signal: Signal,
        order_result: OrderResult,
    ) -> Position:
        """Record a new open position."""
        position = Position(
            market_slug=market.slug,
            token_id=signal.bet_token_id,
            direction=signal.direction,
            entry_price=signal.market_prob,
            cost_basis=order_result.cost or 0.0,
            order_id=order_result.order_id or "unknown",
            entry_time=time.time(),
            window_end=market.window_end.timestamp(),
        )
        self.positions.append(position)

        # Log the trade
        record = TradeRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            market_slug=market.slug,
            question=market.question,
            direction=signal.direction,
            edge=signal.edge,
            confidence=signal.confidence,
            market_prob=signal.market_prob,
            bet_size=order_result.cost or 0.0,
            order_id=order_result.order_id or "unknown",
            outcome="PENDING",
            pnl=0.0,
            capital_after=0.0,
            reasoning=signal.reasoning,
        )
        self.trade_history.append(record)
        self.total_trades += 1

        logger.info(
            f"POSITION OPENED: {signal.direction} on {market.slug} | "
            f"Cost: ${order_result.cost:.2f} | Edge: {signal.edge:.1%}"
        )

        return position

    def resolve_position(self, position: Position, won: bool, capital_after: float):
        """Resolve a position as won or lost."""
        if won:
            # Shares pay $1 each. Profit = payout - cost
            payout = position.cost_basis / position.entry_price  # num shares * $1
            position.pnl = payout - position.cost_basis
            position.status = "WON"
            self.wins += 1
        else:
            position.pnl = -position.cost_basis
            position.status = "LOST"
            self.losses += 1

        position.exit_time = time.time()
        self.total_pnl += position.pnl

        # Update the trade record
        for record in reversed(self.trade_history):
            if record.order_id == position.order_id:
                record.outcome = "WIN" if won else "LOSS"
                record.pnl = position.pnl
                record.capital_after = capital_after
                break

        emoji = "WIN" if won else "LOSS"
        logger.info(
            f"POSITION RESOLVED: {emoji} | {position.direction} on "
            f"{position.market_slug} | PnL: ${position.pnl:+.2f}"
        )

    def get_open_positions(self) -> list[Position]:
        """Return all open positions."""
        return [p for p in self.positions if p.status == "OPEN"]

    def get_expired_positions(self) -> list[Position]:
        """Return open positions whose market window has ended."""
        now = time.time()
        return [
            p for p in self.positions
            if p.status == "OPEN" and now > p.window_end + 30  # 30s buffer
        ]

    def get_summary(self) -> dict:
        """Get a summary of trading performance."""
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0
        avg_win = 0.0
        avg_loss = 0.0
        if self.wins > 0:
            avg_win = sum(p.pnl for p in self.positions if p.status == "WON") / self.wins
        if self.losses > 0:
            avg_loss = sum(p.pnl for p in self.positions if p.status == "LOST") / self.losses

        # Streak tracking
        streak = 0
        streak_type = ""
        for p in reversed(self.positions):
            if p.status == "OPEN":
                continue
            if not streak_type:
                streak_type = p.status
                streak = 1
            elif p.status == streak_type:
                streak += 1
            else:
                break

        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": f"{win_rate:.1f}%",
            "total_pnl": f"${self.total_pnl:+.2f}",
            "avg_win": f"${avg_win:+.2f}",
            "avg_loss": f"${avg_loss:+.2f}",
            "open_positions": len(self.get_open_positions()),
            "streak": f"{streak} {streak_type}" if streak_type else "None",
        }

    def save_to_file(self, filepath: str = "trades.json"):
        """Save trade history to a JSON file."""
        try:
            data = {
                "summary": self.get_summary(),
                "trades": [asdict(r) for r in self.trade_history],
            }
            os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
            logger.info(f"Trade history saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")

    def print_status(self, risk_manager):
        """Print a formatted status update with compounding growth metrics."""
        summary = self.get_summary()
        open_positions = self.get_open_positions()
        status = risk_manager.get_status()
        capital = risk_manager.current_capital
        # Use live starting capital (set on first wallet sync) when available,
        # so the growth % reflects what's actually happened in this session
        # rather than progress against the hardcoded $150.
        baseline = (
            risk_manager._live_starting_capital
            if risk_manager._live_starting_capital is not None
            else config.STARTING_CAPITAL
        )
        growth = ((capital - baseline) / baseline) * 100 if baseline else 0.0
        next_max = max(config.MAX_BET_SIZE, capital * config.MAX_BET_FRACTION)

        print("\n" + "=" * 60)
        print(f"  POLYMARKET BTC BOT - 24/7 COMPOUNDING")
        print("-" * 60)
        print(f"  Capital:   ${capital:.2f}  ({growth:+.1f}% from ${baseline:.2f})")
        print(f"  Peak:      ${risk_manager.peak_capital:.2f}")
        print(f"  Total PnL: {summary['total_pnl']}")
        print(f"  Next Max Trade: ${next_max:.2f}")
        print("-" * 60)
        print(
            f"  Trades: {summary['total_trades']} | "
            f"W/L: {summary['wins']}/{summary['losses']} | "
            f"Win Rate: {summary['win_rate']}"
        )
        print(
            f"  Avg Win: {summary['avg_win']} | "
            f"Avg Loss: {summary['avg_loss']} | "
            f"Streak: {summary['streak']}"
        )
        print(f"  Exposure: ${status['total_exposure']:.2f} | Available: ${status['available']:.2f}")
        if open_positions:
            print(f"  Open Positions ({len(open_positions)}):")
            for pos in open_positions:
                secs_left = max(0, pos.window_end - time.time())
                print(
                    f"    - {pos.direction} {pos.market_slug} | "
                    f"${pos.cost_basis:.2f} | {secs_left:.0f}s left"
                )
        print("=" * 60 + "\n")
