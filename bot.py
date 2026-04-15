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
    Autonomous 24/7 Polymarket BTC 5-minute market trading bot.

    Runs continuously with no daily limits. Profits compound into
    larger trade sizes for accelerating growth.

    Main loop:
    1. Discover active BTC 5-minute markets
    2. Wait until T-60 seconds before window closes
    3. Fetch BTC price + momentum data
    4. Analyze for edge vs market prices
    5. If edge found, size the bet (scales with capital) and execute
    6. Resolve expired positions, reinvest profits, repeat 24/7
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
        self._cycle_count = 0
        self._start_time = time.time()

    def initialize(self):
        """Set up connections and verify everything works."""
        mode_str = "DRY RUN (paper trading)" if self.dry_run else "LIVE TRADING 24/7"
        max_trade = f"${config.MAX_BET_SIZE:.0f} (scales with growth)"

        print("\n" + "=" * 60)
        print("  POLYMARKET BTC 5-MINUTE TRADING BOT")
        print("  >> AGGRESSIVE COMPOUNDING MODE <<")
        print("=" * 60)
        print(f"  Mode:           {mode_str}")
        print(f"  Starting Cap:   ${config.STARTING_CAPITAL:.2f}")
        print(f"  Max Trade Size: {max_trade}")
        print(f"  Max Bet %:      {config.MAX_BET_FRACTION:.0%} of capital")
        print(f"  Min Edge:       {config.MIN_EDGE_THRESHOLD:.0%}")
        print(f"  Kelly Fraction: {config.KELLY_FRACTION}")
        print(f"  Compounding:    {'ON' if config.COMPOUND_PROFITS else 'OFF'}")
        print(f"  Trading:        24/7 - No daily limits")
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

        print(f"\n  Bot initialized. Trading 24/7...\n")

    def run(self):
        """Main trading loop. Runs 24/7 until manually interrupted."""
        self._running = True
        self._start_time = time.time()

        while self._running:
            try:
                self._run_cycle()
                self._cycle_count += 1
            except KeyboardInterrupt:
                logger.info("Shutdown requested by user.")
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)
                # Brief pause on error, then keep going
                time.sleep(5)

        self._shutdown()

    def _run_cycle(self):
        """Execute one full trading cycle."""
        # Step 0: Sync capital with live wallet balance (live mode only).
        # Dry run keeps its simulated capital so PnL math stays consistent.
        if not self.dry_run:
            self._sync_live_capital()

        # Step 1: Resolve any expired positions (collect profits)
        self._resolve_expired_positions()

        # Step 2: Check if we can trade (only blocked by max positions or zero capital)
        risk_status = self.risk_manager.get_status()
        if not risk_status["can_trade"]:
            logger.info(
                f"Waiting for positions to resolve. "
                f"Open: {risk_status['open_positions']}, "
                f"Available: ${risk_status['available']:.2f}"
            )
            time.sleep(config.SCAN_INTERVAL_SECONDS)
            return

        # Step 3: Find active BTC 5-minute markets
        markets = self.scanner.find_active_btc_5min_markets()
        if not markets:
            logger.debug("No active BTC 5-min markets found. Scanning again...")
            time.sleep(config.SCAN_INTERVAL_SECONDS)
            return

        # Step 4: Process each market
        traded = False
        for market in markets:
            seconds_left = market.seconds_until_close

            # Wait for entry window if needed
            if seconds_left > config.ENTRY_SECONDS_BEFORE_CLOSE:
                wait_time = seconds_left - config.ENTRY_SECONDS_BEFORE_CLOSE
                if wait_time <= config.ENTRY_SECONDS_BEFORE_CLOSE:
                    logger.info(
                        f"Market {market.slug}: {seconds_left:.0f}s left. "
                        f"Waiting {wait_time:.0f}s for optimal entry..."
                    )
                    time.sleep(wait_time)
                    seconds_left = market.seconds_until_close
                else:
                    continue

            if seconds_left < config.LATEST_ENTRY_SECONDS:
                logger.debug(f"Market {market.slug}: too late ({seconds_left:.0f}s)")
                continue

            # Skip markets we've already bet on this window
            if self.risk_manager.has_traded_window(market):
                logger.debug(
                    f"Market {market.slug}: already bet on this window, skipping."
                )
                continue

            # Step 5: Analyze and trade
            if self._analyze_and_trade(market):
                traded = True

        # Print status every few cycles
        if self._cycle_count % 3 == 0 or traded:
            self.tracker.print_status(self.risk_manager)

        # Wait for next scan
        secs_to_next = self.scanner.seconds_until_window_close()
        if secs_to_next > config.ENTRY_SECONDS_BEFORE_CLOSE:
            sleep_time = secs_to_next - config.ENTRY_SECONDS_BEFORE_CLOSE
            logger.info(f"Next window entry in {sleep_time:.0f}s.")
            time.sleep(min(sleep_time, config.SCAN_INTERVAL_SECONDS))
        else:
            time.sleep(3)  # Brief pause between rapid scans

    def _analyze_and_trade(self, market) -> bool:
        """Fetch data, run strategy, and potentially execute a trade. Returns True if traded."""
        # Fetch current BTC price
        price_snapshot = self.price_feed.get_current_price()
        if not price_snapshot:
            logger.warning("Could not get BTC price. Skipping market.")
            return False

        # Fetch candles and compute momentum
        candles = self.price_feed.get_recent_candles(
            interval="1m", limit=config.LOOKBACK_CANDLES
        )
        if not candles:
            logger.warning("Could not get candle data. Skipping market.")
            return False

        momentum = self.price_feed.compute_momentum(candles)
        if not momentum:
            logger.warning("Could not compute momentum. Skipping market.")
            return False

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
            return False

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
            return False

        # Risk check (sizing scales with capital)
        risk_decision = self.risk_manager.evaluate_trade(signal, market=market)
        if not risk_decision.approved:
            logger.info(f"Risk check: {risk_decision.reason}")
            return False

        # Execute the trade
        logger.info(
            f"EXECUTING TRADE: {signal.direction} ${risk_decision.position_size:.2f} "
            f"on {market.slug} | Capital: ${self.risk_manager.current_capital:.2f}"
        )

        order_result = self.executor.place_market_order(
            token_id=signal.bet_token_id,
            amount=risk_decision.position_size,
        )

        if order_result.success:
            position = self.tracker.open_position(market, signal, order_result)
            self.risk_manager.record_trade_opened(
                order_result.cost or risk_decision.position_size,
                market=market,
            )
            logger.info(f"Trade executed. Order ID: {order_result.order_id}")
            return True
        else:
            logger.warning(f"Trade failed: {order_result.error}")
            return False

    def _sync_live_capital(self):
        """Pull the live USDC balance from Polymarket and update capital."""
        balance = self.poly_client.get_usdc_balance()
        if balance < 0:
            # Fetch failed - carry on with what we had.
            return
        prev = self.risk_manager.current_capital
        self.risk_manager.refresh_capital_from_wallet(balance)
        new = self.risk_manager.current_capital
        if abs(new - prev) > 0.01:
            logger.info(
                f"Wallet sync: ${prev:.2f} -> ${new:.2f} "
                f"(free ${balance:.2f} + exposure ${self.risk_manager.total_exposure:.2f})"
            )

    def _resolve_expired_positions(self):
        """Check and resolve positions whose markets have expired. Profits flow back to capital."""
        expired = self.tracker.get_expired_positions()
        if not expired:
            return

        for position in expired:
            won = self._determine_outcome(position)

            self.tracker.resolve_position(
                position, won, self.risk_manager.current_capital
            )
            self.risk_manager.record_trade_closed(position.cost_basis, position.pnl)

            # Log compounding effect
            if won and position.pnl > 0:
                baseline = (
                    self.risk_manager._live_starting_capital
                    or config.STARTING_CAPITAL
                )
                growth = ((self.risk_manager.current_capital - baseline) / baseline) * 100
                logger.info(
                    f"PROFIT COMPOUNDED: +${position.pnl:.2f} -> "
                    f"Capital now ${self.risk_manager.current_capital:.2f} ({growth:+.1f}% growth)"
                )

        # Save trade log after resolutions
        self.tracker.save_to_file("trades.json")

    def _determine_outcome(self, position) -> bool:
        """
        Determine if a position won or lost.

        For dry run: use current BTC price vs the inferred strike.
        For live: query Polymarket for resolution, fallback to BTC price.
        """
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

        # Fallback: check token price on Polymarket
        token_price = self.poly_client.get_last_trade_price(position.token_id)
        if token_price > 0.8:
            return True
        elif token_price < 0.2:
            return False

        logger.warning(
            f"Could not determine outcome for {position.market_slug}. "
            f"Token price: {token_price}. Assuming loss."
        )
        return False

    def _shutdown(self):
        """Clean shutdown."""
        print("\nShutting down bot...")
        self.tracker.save_to_file("trades.json")
        self.tracker.print_status(self.risk_manager)

        uptime = time.time() - self._start_time
        hours = uptime / 3600
        summary = self.tracker.get_summary()
        baseline = (
            self.risk_manager._live_starting_capital
            or config.STARTING_CAPITAL
        )
        growth = ((self.risk_manager.current_capital - baseline) / baseline) * 100

        print(f"\n  SESSION SUMMARY")
        print(f"  {'='*40}")
        print(f"  Uptime:         {hours:.1f} hours")
        print(f"  Total Trades:   {summary['total_trades']}")
        print(f"  Win Rate:       {summary['win_rate']}")
        print(f"  Total PnL:      {summary['total_pnl']}")
        print(f"  Starting Cap:   ${baseline:.2f}")
        print(f"  Final Capital:  ${self.risk_manager.current_capital:.2f}")
        print(f"  Growth:         {growth:+.1f}%")
        print(f"  Peak Capital:   ${self.risk_manager.peak_capital:.2f}")

        # Cancel any open orders on shutdown
        if self.executor and not self.dry_run:
            self.executor.cancel_all_orders()
