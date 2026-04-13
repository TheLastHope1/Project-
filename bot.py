import logging
import time
import sys
from datetime import datetime, timezone

import config
from polymarket_client import PolymarketClient
from market_scanner import MarketScanner
from price_feed import BinancePriceFeed
from strategy import TradingStrategy
from risk_manager import RiskManager
from executor import OrderExecutor
from tracker import TradeTracker

logger = logging.getLogger("polymarket_bot")


class TradingBot:
    """
    Autonomous Polymarket BTC 5-minute market trading bot.

    Main loop:
    1. Discover active BTC 5-minute markets
    2. Wait until T-45 seconds before window closes
    3. Fetch BTC price + momentum data
    4. Analyze for edge vs market prices
    5. If edge found, size the bet and execute
    6. Resolve expired positions and track P&L
    """

    def __init__(self, dry_run: bool = None):
        self.dry_run = dry_run if dry_run is not None else config.DRY_RUN

        # Initialize components
        self.poly_client = PolymarketClient()
        self.scanner = MarketScanner()
        self.price_feed = BinancePriceFeed()
        self.strategy = TradingStrategy()
        self.risk_manager = RiskManager()
        self.executor = None  # Initialized after client connection
        self.tracker = TradeTracker()

        self._running = False
        self._last_daily_reset = self._get_utc_date()

    def initialize(self):
        """Set up connections and verify everything works."""
        print("\n" + "=" * 60)
        print("  POLYMARKET BTC 5-MINUTE TRADING BOT")
        print("=" * 60)
        print(f"  Mode: {'DRY RUN (paper trading)' if self.dry_run else 'LIVE TRADING'}")
        print(f"  Starting Capital: ${config.STARTING_CAPITAL:.2f}")
        print(f"  Max Bet Size: ${config.MAX_BET_SIZE:.2f}")
        print(f"  Min Edge: {config.MIN_EDGE_THRESHOLD:.0%}")
        print(f"  Daily Loss Limit: ${config.MAX_DAILY_LOSS:.2f}")
        print("=" * 60 + "\n")

        # Initialize Polymarket client
        self.poly_client.initialize()
        self.executor = OrderExecutor(
            self.poly_client.get_client(),
            dry_run=self.dry_run,
        )

        # Quick connectivity check
        price = self.price_feed.get_current_price()
        if price:
            print(f"  BTC Price: ${price.price:,.2f}")
        else:
            print("  WARNING: Could not fetch BTC price from Binance")

        print(f"\n  Bot initialized. Entering trading loop...\n")

    def run(self):
        """Main trading loop. Runs until interrupted."""
        self._running = True

        while self._running:
            try:
                self._run_cycle()
            except KeyboardInterrupt:
                logger.info("Shutdown requested.")
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)
                time.sleep(10)  # Brief pause on error

        self._shutdown()

    def _run_cycle(self):
        """Execute one full trading cycle."""
        # Check for daily reset
        today = self._get_utc_date()
        if today != self._last_daily_reset:
            self.risk_manager.reset_daily()
            self._last_daily_reset = today

        # Step 1: Resolve any expired positions
        self._resolve_expired_positions()

        # Step 2: Check if we can trade
        risk_status = self.risk_manager.get_status()
        if not risk_status["can_trade"]:
            logger.info(f"Cannot trade right now. Risk status: {risk_status}")
            self.tracker.print_status(self.risk_manager.current_capital)
            time.sleep(config.SCAN_INTERVAL_SECONDS)
            return

        # Step 3: Find active BTC 5-minute markets
        markets = self.scanner.find_active_btc_5min_markets()
        if not markets:
            logger.debug("No active BTC 5-min markets found. Waiting...")
            time.sleep(config.SCAN_INTERVAL_SECONDS)
            return

        # Step 4: Process each market
        for market in markets:
            seconds_left = market.seconds_until_close

            # Check timing window
            if seconds_left > config.ENTRY_SECONDS_BEFORE_CLOSE:
                wait_time = seconds_left - config.ENTRY_SECONDS_BEFORE_CLOSE
                logger.info(
                    f"Market {market.slug}: {seconds_left:.0f}s left. "
                    f"Waiting {wait_time:.0f}s for entry window..."
                )
                if wait_time > 0 and wait_time <= config.ENTRY_SECONDS_BEFORE_CLOSE:
                    time.sleep(wait_time)
                    # Refresh seconds_left after sleeping
                    seconds_left = market.seconds_until_close
                else:
                    continue

            if seconds_left < config.LATEST_ENTRY_SECONDS:
                logger.debug(f"Market {market.slug}: too late ({seconds_left:.0f}s)")
                continue

            # Step 5: Gather data and analyze
            self._analyze_and_trade(market)

        # Print status periodically
        self.tracker.print_status(self.risk_manager.current_capital)

        # Wait for next scan
        secs_to_next = self.scanner.seconds_until_window_close()
        if secs_to_next > config.ENTRY_SECONDS_BEFORE_CLOSE:
            # Sleep until the entry window of the next cycle
            sleep_time = secs_to_next - config.ENTRY_SECONDS_BEFORE_CLOSE
            logger.info(f"Next entry window in {sleep_time:.0f}s. Sleeping...")
            time.sleep(min(sleep_time, config.SCAN_INTERVAL_SECONDS))
        else:
            time.sleep(5)  # Brief pause between scans

    def _analyze_and_trade(self, market):
        """Fetch data, run strategy, and potentially execute a trade."""
        # Fetch current BTC price
        price_snapshot = self.price_feed.get_current_price()
        if not price_snapshot:
            logger.warning("Could not get BTC price. Skipping market.")
            return

        # Fetch candles and compute momentum
        candles = self.price_feed.get_recent_candles(
            interval="1m", limit=config.LOOKBACK_CANDLES
        )
        if not candles:
            logger.warning("Could not get candle data. Skipping market.")
            return

        momentum = self.price_feed.compute_momentum(candles)
        if not momentum:
            logger.warning("Could not compute momentum. Skipping market.")
            return

        # Fetch Polymarket prices
        yes_price = self.poly_client.get_midpoint(market.yes_token_id)
        no_price = self.poly_client.get_midpoint(market.no_token_id)

        # Fallback: if midpoint fails, try get_price
        if yes_price <= 0:
            yes_price = self.poly_client.get_price(market.yes_token_id, "buy")
        if no_price <= 0:
            no_price = self.poly_client.get_price(market.no_token_id, "buy")

        # If we still can't get prices, use complement
        if yes_price > 0 and no_price <= 0:
            no_price = max(0.01, 1.0 - yes_price)
        elif no_price > 0 and yes_price <= 0:
            yes_price = max(0.01, 1.0 - no_price)

        if yes_price <= 0 or no_price <= 0:
            logger.warning(
                f"Could not get market prices for {market.slug}. "
                f"YES: {yes_price}, NO: {no_price}"
            )
            return

        logger.info(
            f"Market: {market.question} | "
            f"BTC: ${price_snapshot.price:,.2f} | Strike: ${market.strike_price:,.2f} | "
            f"YES: {yes_price:.3f} NO: {no_price:.3f} | "
            f"{market.seconds_until_close:.0f}s left"
        )

        # Run strategy
        signal = self.strategy.analyze(
            market=market,
            price=price_snapshot,
            momentum=momentum,
            yes_price=yes_price,
            no_price=no_price,
        )

        if not signal:
            logger.debug(f"No signal for {market.slug}.")
            return

        # Risk check
        risk_decision = self.risk_manager.evaluate_trade(signal)
        if not risk_decision.approved:
            logger.info(f"Risk rejected: {risk_decision.reason}")
            return

        # Execute!
        logger.info(
            f"EXECUTING TRADE: {signal.direction} ${risk_decision.position_size:.2f} "
            f"on {market.slug}"
        )

        order_result = self.executor.place_market_order(
            token_id=signal.bet_token_id,
            amount=risk_decision.position_size,
        )

        if order_result.success:
            # Record the position
            position = self.tracker.open_position(market, signal, order_result)
            self.risk_manager.record_trade_opened(order_result.cost or risk_decision.position_size)
            logger.info(f"Trade executed successfully. Order ID: {order_result.order_id}")
        else:
            logger.warning(f"Trade failed: {order_result.error}")

    def _resolve_expired_positions(self):
        """Check and resolve positions whose markets have expired."""
        expired = self.tracker.get_expired_positions()
        if not expired:
            return

        for position in expired:
            # Determine outcome
            # For BTC 5-min markets: if we bought YES and BTC finished above strike, we win
            # We need the final BTC price to determine this
            won = self._determine_outcome(position)

            self.tracker.resolve_position(
                position, won, self.risk_manager.current_capital
            )
            self.risk_manager.record_trade_closed(position.cost_basis, position.pnl)

        # Save trade log after resolutions
        self.tracker.save_to_file("trades.json")

    def _determine_outcome(self, position) -> bool:
        """
        Determine if a position won or lost.

        For dry run: use current BTC price vs the inferred strike.
        For live: ideally query Polymarket for resolution, but we can
        also use BTC price as a proxy since these are binary BTC markets.
        """
        # Get the market info to find the strike price
        # Since we store the slug, try to reconstruct
        price = self.price_feed.get_current_price()
        if not price:
            logger.warning("Cannot determine outcome without price data. Assuming loss.")
            return False

        # Try to find the market to get the strike price
        market = self.scanner._fetch_market_by_slug(position.market_slug)
        if market and market.strike_price > 0:
            btc_above_strike = price.price > market.strike_price
            if position.direction == "YES":
                return btc_above_strike
            else:
                return not btc_above_strike

        # Fallback: if we can't get market data, check token price
        # If our token price went to ~1.0, we won; if ~0.0, we lost
        token_price = self.poly_client.get_last_trade_price(position.token_id)
        if token_price > 0.8:
            return True
        elif token_price < 0.2:
            return False

        # If we can't determine, log and assume loss (conservative)
        logger.warning(
            f"Could not determine outcome for {position.market_slug}. "
            f"Token price: {token_price}. Assuming loss."
        )
        return False

    def _shutdown(self):
        """Clean shutdown."""
        print("\nShutting down...")
        self.tracker.save_to_file("trades.json")
        self.tracker.print_status(self.risk_manager.current_capital)

        summary = self.tracker.get_summary()
        print(f"\nFinal Summary:")
        print(f"  Total Trades: {summary['total_trades']}")
        print(f"  Win Rate: {summary['win_rate']}")
        print(f"  Total PnL: {summary['total_pnl']}")
        print(f"  Final Capital: ${self.risk_manager.current_capital:.2f}")

        # Cancel any open orders on shutdown
        if self.executor and not self.dry_run:
            self.executor.cancel_all_orders()

    def _get_utc_date(self) -> str:
        """Get current UTC date as string."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
