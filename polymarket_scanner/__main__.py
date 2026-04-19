"""CLI entry point: `python -m polymarket_scanner`."""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta

from .client import PolymarketClient
from .notifier import build_default_notifier
from .scanner import ScanConfig, run_forever, scan_once


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="polymarket_scanner",
        description="Scan Polymarket for forfeit-edge underdog opportunities.",
    )
    p.add_argument("--once", action="store_true",
                   help="Run a single scan and exit (for cron/testing).")
    p.add_argument("--interval", type=int, default=120,
                   help="Seconds between scans when running continuously.")
    p.add_argument("--max-price", type=float, default=0.40,
                   help="Only alert when the underdog trades at or below this price.")
    p.add_argument("--min-liquidity", type=float, default=500.0,
                   help="Skip markets with less than this much liquidity (USDC).")
    p.add_argument("--min-volume", type=float, default=100.0,
                   help="Skip markets with less than this much 24h volume.")
    p.add_argument("--watchlist", nargs="*", default=[],
                   help="Team / entity substrings to match against question text.")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = ScanConfig(
        max_underdog_price=args.max_price,
        min_liquidity=args.min_liquidity,
        min_volume=args.min_volume,
        team_watchlist=tuple(args.watchlist),
        scan_interval=timedelta(seconds=args.interval),
    )
    client = PolymarketClient()
    notify = build_default_notifier()

    if args.once:
        for opp in scan_once(client, cfg):
            notify(opp)
        return 0

    try:
        run_forever(client, cfg, notify)
    except KeyboardInterrupt:
        print("\ninterrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
