#!/usr/bin/env python3
"""
Polymarket BTC 5-Minute Trading Bot

Usage:
    python run.py              # Run in dry-run mode (default)
    python run.py --live       # Run with real money
    python run.py --dry-run    # Explicitly run in paper trading mode
"""

import argparse
import logging
import sys
import os


def setup_logging():
    """Configure logging for the bot."""
    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    # File handler
    os.makedirs("logs", exist_ok=True)
    file_handler = logging.FileHandler("logs/bot.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Root logger
    root_logger = logging.getLogger("polymarket_bot")
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return root_logger


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket BTC 5-Minute Trading Bot"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Force live trading (overrides DRY_RUN in .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force paper trading (overrides DRY_RUN in .env)",
    )
    args = parser.parse_args()

    # Setup
    logger = setup_logging()

    # Load .env BEFORE reading config.DRY_RUN
    from dotenv import load_dotenv
    load_dotenv()

    # Determine mode: .env is authoritative, CLI flags can override.
    import config
    if args.live:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = config.DRY_RUN

    if not dry_run:
        print("\n" + "!" * 60)
        print("  WARNING: LIVE TRADING MODE")
        print("  Real money will be used. Press Ctrl+C to cancel.")
        print("!" * 60)
        try:
            import time
            for i in range(5, 0, -1):
                print(f"  Starting in {i}...")
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Cancelled.")
            sys.exit(0)

    if not os.getenv("PRIVATE_KEY"):
        print("\nERROR: No credentials found.")
        print("Please copy .env.example to .env and fill in your credentials.")
        print("\nRequired:")
        print("  PRIVATE_KEY - Your Polygon wallet private key")
        print("\nOptional (will be derived if not provided):")
        print("  POLYMARKET_API_KEY")
        print("  POLYMARKET_API_SECRET")
        print("  POLYMARKET_API_PASSPHRASE")
        print("\nSee README.md for setup instructions.")
        sys.exit(1)

    # Run the bot
    from bot import TradingBot

    bot = TradingBot(dry_run=dry_run)
    try:
        bot.initialize()
        bot.run()
    except KeyboardInterrupt:
        print("\nBot stopped.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
