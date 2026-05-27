"""CLI entry point: `python -m polymarket_scanner`."""
from __future__ import annotations

import argparse
import logging
import os
from datetime import timedelta
from pathlib import Path

from .client import PolymarketClient
from .notifier import build_default_notifier
from .scanner import ScanConfig, run_forever, scan_once


def _load_env_file(path: Path) -> None:
    """Poor man's dotenv - no extra dep. Lines like KEY=value, skip blanks/#."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="polymarket_scanner",
        description="Scan Polymarket for forfeit-edge underdog opportunities.",
    )
    p.add_argument("--once", action="store_true",
                   help="Run a single scan and exit (for cron/testing).")
    p.add_argument("--interval", type=int,
                   default=int(os.environ.get("POLY_INTERVAL", "120")),
                   help="Seconds between scans when running continuously.")
    p.add_argument("--max-price", type=float,
                   default=float(os.environ.get("POLY_MAX_PRICE", "0.40")),
                   help="Only alert when the underdog executable/screen price is at or below this price.")
    p.add_argument("--max-screen-price", type=float,
                   default=float(os.environ.get("POLY_MAX_SCREEN_PRICE", "0.49")),
                   help="Broad Gamma screen threshold before CLOB enrichment.")
    p.add_argument("--min-liquidity", type=float,
                   default=float(os.environ.get("POLY_MIN_LIQUIDITY", "500")),
                   help="Skip markets with less than this much liquidity (USDC).")
    p.add_argument("--min-volume", type=float,
                   default=float(os.environ.get("POLY_MIN_VOLUME", "100")),
                   help="Skip markets with less than this much 24h volume.")
    p.add_argument("--watchlist", nargs="*",
                   default=_split_csv(os.environ.get("POLY_WATCHLIST")),
                   help="Team / entity substrings to match against question text. "
                        "Can also be set via POLY_WATCHLIST=FaZe,G2,NAVI")
    p.add_argument("--use-clob-prices", action=argparse.BooleanOptionalAction,
                   default=os.environ.get("POLY_USE_CLOB_PRICES", "1").lower() not in {"0", "false", "no", "off"},
                   help="Probe public CLOB best ask/bid prices for screened candidates.")
    p.add_argument("--require-clob-price", action="store_true",
                   default=os.environ.get("POLY_REQUIRE_CLOB_PRICE", "0").lower() in {"1", "true", "yes", "on"},
                   help="Drop alerts when CLOB executable price cannot be fetched.")
    p.add_argument("--max-clob-probes", type=int,
                   default=int(os.environ.get("POLY_MAX_CLOB_PROBES", "80")),
                   help="Max candidate token IDs to probe on CLOB per scan.")
    p.add_argument("--fee-bps", type=float,
                   default=float(os.environ.get("POLY_FEE_BPS", "0")),
                   help="Conservative fee haircut in basis points for net-edge display.")
    p.add_argument("--slippage-buffer-bps", type=float,
                   default=float(os.environ.get("POLY_SLIPPAGE_BUFFER_BPS", "0")),
                   help="Extra slippage haircut in basis points for net-edge display.")
    p.add_argument("--verbose", "-v", action="store_true",
                   default=os.environ.get("POLY_VERBOSE") == "1")
    return p.parse_args()


def main() -> int:
    # Load scanner.env from the current working dir before parsing args so
    # env-backed defaults pick up values from the file.
    _load_env_file(Path.cwd() / "scanner.env")

    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = ScanConfig(
        max_underdog_price=args.max_price,
        max_screen_price=args.max_screen_price,
        min_liquidity=args.min_liquidity,
        min_volume=args.min_volume,
        team_watchlist=tuple(args.watchlist),
        scan_interval=timedelta(seconds=args.interval),
        use_clob_prices=args.use_clob_prices,
        require_clob_price=args.require_clob_price,
        max_clob_probes_per_scan=args.max_clob_probes,
        fee_bps=args.fee_bps,
        slippage_buffer_bps=args.slippage_buffer_bps,
    )
    client = PolymarketClient()
    notify = build_default_notifier()

    if args.watchlist:
        logging.getLogger(__name__).info("watchlist active: %s", ", ".join(args.watchlist))

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
