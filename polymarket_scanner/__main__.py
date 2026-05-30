"""CLI entry point: `python -m polymarket_scanner`.

Modes:

    python -m polymarket_scanner --once          # single scan, exit
    python -m polymarket_scanner                 # poll forever
    python -m polymarket_scanner --validate-side-semantics <token_id>
                                                 # check /price vs /book
    python -m polymarket_scanner --journal-pnl   # realised PnL summary
    python -m polymarket_scanner --journal-export out.jsonl
                                                 # dump opportunities table

All scanning paths share ``ScanConfig`` so behaviour is identical across the
CLI, the web dashboard, and the background scanner thread.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .client import PolymarketClient
from .journal import Journal, make_journal
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


def _bool_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="polymarket_scanner",
        description="Polymarket edge scanner (read-only by default).",
    )
    # ---- run modes ----
    p.add_argument("--once", action="store_true",
                   help="Run a single scan and exit (for cron/testing).")
    p.add_argument("--validate-side-semantics", metavar="TOKEN_ID",
                   help="Cross-check /price BUY/SELL semantics against /book "
                        "for one token. Exits non-zero on mismatch.")
    p.add_argument("--journal-pnl", action="store_true",
                   help="Print the realised-PnL summary from the journal and exit.")
    p.add_argument("--journal-export", metavar="PATH",
                   help="Stream the opportunities table as JSONL to PATH and exit.")
    p.add_argument("--journal-path",
                   default=os.environ.get("POLY_JOURNAL_PATH", "journal.db"),
                   help="SQLite journal file. Defaults to ./journal.db or $POLY_JOURNAL_PATH. "
                        "Ignored if --journal-url is set.")
    p.add_argument("--journal-url",
                   default=os.environ.get("POLY_JOURNAL_URL"),
                   help="Postgres connection string (postgres://...) for the durable journal "
                        "backend. Use this for Vercel/serverless deploys. Supports Supabase, "
                        "Vercel Postgres, Neon, or any Postgres.")

    # ---- scanning config ----
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
                   help="Team / entity substrings to match against question text.")

    # ---- pricing source ----
    p.add_argument("--use-book", action=argparse.BooleanOptionalAction,
                   default=_bool_env("POLY_USE_BOOK", "1"),
                   help="Use the /book endpoint (depth-aware) instead of /price.")
    p.add_argument("--use-clob-prices", action=argparse.BooleanOptionalAction,
                   default=_bool_env("POLY_USE_CLOB_PRICES", "1"),
                   help="Fall back to /price when /book is unavailable.")
    p.add_argument("--require-clob-price", action="store_true",
                   default=_bool_env("POLY_REQUIRE_CLOB_PRICE", "0"),
                   help="Drop alerts when CLOB executable price cannot be fetched.")
    p.add_argument("--max-clob-probes", type=int,
                   default=int(os.environ.get("POLY_MAX_CLOB_PROBES", "80")),
                   help="Max candidate token IDs to probe on CLOB per scan.")
    p.add_argument("--use-clob-fee-rate", action="store_true",
                   default=_bool_env("POLY_USE_CLOB_FEE_RATE", "0"),
                   help="Fetch the per-token fee rate from /fee-rate instead of "
                        "using the category heuristic. Adds one API call per "
                        "candidate.")
    p.add_argument("--fee-rate-override", type=float,
                   default=float(os.environ["POLY_FEE_RATE_OVERRIDE"])
                           if os.environ.get("POLY_FEE_RATE_OVERRIDE") else None,
                   help="Force a single fee rate (e.g. 0.03). Useful for "
                        "back-testing under hypothetical fee schedules.")

    # ---- paper trade / journal ----
    p.add_argument("--paper-notional", type=float,
                   default=float(os.environ.get("POLY_PAPER_NOTIONAL", "100")),
                   help="USDC notional per simulated entry. Drives the depth-aware "
                        "VWAP calculation persisted in the journal.")
    p.add_argument("--persist", action=argparse.BooleanOptionalAction,
                   default=_bool_env("POLY_PERSIST", "1"),
                   help="Write every opportunity snapshot to the SQLite journal.")

    # ---- rule classifier gates ----
    p.add_argument("--strict-rule-class", action="store_true",
                   default=_bool_env("POLY_STRICT_RULE_CLASS", "0"),
                   help="Reject markets whose rule class falls into the "
                        "never-trade set (OTHER_OUTCOME, REFUND_VOID, "
                        "UNKNOWN_EXPLICIT, TIE_ONLY).")
    p.add_argument("--min-rule-confidence", type=float,
                   default=float(os.environ.get("POLY_MIN_RULE_CONFIDENCE", "0.0")),
                   help="Drop candidates whose rule classifier confidence is "
                        "below this threshold (0.0 = keep everything).")
    p.add_argument("--min-p50", type=float,
                   default=float(os.environ.get("POLY_MIN_P50", "0.0")),
                   help="Drop candidates whose modelled 50/50 probability is "
                        "below this threshold.")

    # ---- legacy / display ----
    p.add_argument("--fee-bps", type=float,
                   default=float(os.environ.get("POLY_FEE_BPS", "0")),
                   help="Legacy bps haircut, only used for the back-compat "
                        "net_edge_pct display field. Real EV uses the official "
                        "fee model.")
    p.add_argument("--slippage-buffer-bps", type=float,
                   default=float(os.environ.get("POLY_SLIPPAGE_BUFFER_BPS", "0")),
                   help="Legacy slippage haircut for the back-compat display.")
    p.add_argument("--verbose", "-v", action="store_true",
                   default=os.environ.get("POLY_VERBOSE") == "1")
    return p.parse_args()


def _format_opportunity_line(opp) -> str:
    """One-line stdout summary of an Opportunity for the CLI."""
    ev = opp.model_ev_pct if opp.model_ev_pct is not None else 0.0
    vwap = opp.vwap_buy if opp.vwap_buy is not None else opp.underdog_price
    fee = opp.fee_rate if opp.fee_rate is not None else 0.0
    rule = opp.rule_class or "no_rule"
    conf = opp.rule_confidence if opp.rule_confidence is not None else 0.0
    return (
        f"score={opp.score:>3}  EV={ev:+.1%}  rule={rule}({conf:.2f})  "
        f"px={opp.underdog_price:.3f}  vwap={vwap:.3f}  fee={fee:.3f}  "
        f"{opp.market.question}"
    )


def _run_validate_side_semantics(token_id: str, journal: Journal | None) -> int:
    client = PolymarketClient()
    result = client.validate_price_side_semantics(token_id)
    print(json.dumps(result, indent=2, default=str))
    if journal is not None:
        try:
            journal.record_side_semantics_check(
                checked_at=datetime.now(timezone.utc),
                token_id=token_id,
                ok=bool(result.get("ok")),
                buy_price=result.get("buy_price"),
                sell_price=result.get("sell_price"),
                best_bid=result.get("best_bid"),
                best_ask=result.get("best_ask"),
                notes=result.get("notes"),
            )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("failed to journal side-semantics check")
    return 0 if result.get("ok") else 2


def _run_journal_pnl(journal: Journal) -> int:
    summary = journal.realised_pnl_summary()
    print(json.dumps(summary, indent=2, default=str))
    return 0


def _run_journal_export(journal: Journal, path: str) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as fp:
        n = journal.export_jsonl(fp)
    print(f"exported {n} rows to {target}")
    return 0


def main() -> int:
    _load_env_file(Path.cwd() / "scanner.env")
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # One journal instance for this process. ``make_journal`` routes
    # ``postgres://`` URLs to PostgresJournal and file paths to SQLite. Passed
    # into ``ScanConfig.journal`` so ``evaluate_markets`` writes here without
    # consulting the module-level singleton.
    journal = make_journal(args.journal_url or args.journal_path)

    # One-off subcommands.
    if args.validate_side_semantics:
        return _run_validate_side_semantics(args.validate_side_semantics, journal)
    if args.journal_pnl:
        return _run_journal_pnl(journal)
    if args.journal_export:
        return _run_journal_export(journal, args.journal_export)

    cfg = ScanConfig(
        max_underdog_price=args.max_price,
        max_screen_price=args.max_screen_price,
        min_liquidity=args.min_liquidity,
        min_volume=args.min_volume,
        team_watchlist=tuple(args.watchlist),
        scan_interval=timedelta(seconds=args.interval),
        use_clob_prices=args.use_clob_prices,
        use_book=args.use_book,
        require_clob_price=args.require_clob_price,
        max_clob_probes_per_scan=args.max_clob_probes,
        use_clob_fee_rate=args.use_clob_fee_rate,
        fee_rate_override=args.fee_rate_override,
        paper_target_notional_usd=args.paper_notional,
        strict_rule_class=args.strict_rule_class,
        min_rule_confidence=args.min_rule_confidence,
        min_probability_fifty=args.min_p50,
        persist_opportunities=args.persist,
        journal=journal,
        fee_bps=args.fee_bps,
        slippage_buffer_bps=args.slippage_buffer_bps,
    )
    client = PolymarketClient()
    notify = build_default_notifier()

    log = logging.getLogger(__name__)
    if args.watchlist:
        log.info("watchlist active: %s", ", ".join(args.watchlist))
    log.info(
        "config: max_price=%.2f screen=%.2f notional=$%.0f persist=%s strict=%s book=%s",
        cfg.max_underdog_price, cfg.max_screen_price, cfg.paper_target_notional_usd,
        cfg.persist_opportunities, cfg.strict_rule_class, cfg.use_book,
    )

    def report(opp) -> None:
        notify(opp)
        print(_format_opportunity_line(opp), flush=True)

    if args.once:
        opps = scan_once(client, cfg)
        for opp in opps:
            report(opp)
        log.info("scan complete: %d opportunities, journal=%d rows total",
                 len(opps), journal.opportunity_count() if cfg.persist_opportunities else -1)
        return 0

    try:
        run_forever(client, cfg, report)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
