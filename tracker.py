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
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": f"{win_rate:.1f}%",
            "total_pnl": f"${self.total_pnl:+.2f}",
            "open_positions": len(self.get_open_positions()),
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

    def print_status(self, capital: float):
        """Print a formatted status update to the console."""
        summary = self.get_summary()
        open_positions = self.get_open_positions()

        print("\n" + "=" * 60)
        print(f"  POLYMARKET BTC BOT STATUS")
        print(f"  Capital: ${capital:.2f} | Total PnL: {summary['total_pnl']}")
        print(
            f"  Trades: {summary['total_trades']} | "
            f"W/L: {summary['wins']}/{summary['losses']} | "
            f"Win Rate: {summary['win_rate']}"
        )
        if open_positions:
            print(f"  Open Positions: {len(open_positions)}")
            for pos in open_positions:
                secs_left = max(0, pos.window_end - time.time())
                print(
                    f"    - {pos.direction} {pos.market_slug} | "
                    f"${pos.cost_basis:.2f} | {secs_left:.0f}s left"
                )
        print("=" * 60 + "\n")
