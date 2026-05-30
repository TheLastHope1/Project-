from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import func, select

from polymarket_edge.arbitrage.binary_scanner import scan_binary_arbitrage
from polymarket_edge.arbitrage.logical_scanner import scan_logical_arbitrage
from polymarket_edge.auth.credential_bootstrap import derive_api_credentials
from polymarket_edge.auth.polymarket_auth import auth_check
from polymarket_edge.backtest.backtester import run_backtest
from polymarket_edge.config import get_settings, reload_settings
from polymarket_edge.db.models import EdgeSnapshot, OrderbookSnapshot, Token
from polymarket_edge.db.session import get_session, init_db
from polymarket_edge.execution.paper_trader import paper_trade_from_latest_edges
from polymarket_edge.ingestion.market_discovery import discover_markets
from polymarket_edge.ingestion.orderbook_poller import poll_orderbooks_loop, poll_orderbooks_once
from polymarket_edge.ingestion.orderbook_ws import stream_orderbooks
from polymarket_edge.ingestion.trades_ingestor import ingest_trades
from polymarket_edge.ingestion.user_ws import stream_user
from polymarket_edge.models.edge_engine import score_market
from polymarket_edge.models.probability import baseline_probability
from polymarket_edge.secrets.manager import redacted_secret_status
from polymarket_edge.secrets.setup_wizard import setup_secrets
from polymarket_edge.trading.client import balances, cancel_all, open_orders
from polymarket_edge.trading.kill_switch import disable_live, reset_live_halt, trigger_kill_switch
from polymarket_edge.trading.preflight import live_preflight


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def _latest_orderbooks(session) -> list[OrderbookSnapshot]:
    subq = (
        select(OrderbookSnapshot.token_id, func.max(OrderbookSnapshot.timestamp).label("max_ts"))
        .group_by(OrderbookSnapshot.token_id)
        .subquery()
    )
    return list(
        session.execute(
            select(OrderbookSnapshot).join(
                subq,
                (OrderbookSnapshot.token_id == subq.c.token_id)
                & (OrderbookSnapshot.timestamp == subq.c.max_ts),
            )
        ).scalars()
    )


def _token_market_map(session) -> dict[str, str]:
    return {token.token_id: token.market_id for token in session.execute(select(Token)).scalars()}


def _scan_edges_latest(session, include_all: bool = False) -> dict[str, int]:
    settings = get_settings()
    snapshots = _latest_orderbooks(session)
    market_by_token = _token_market_map(session)
    saved = 0
    actionable = 0
    n_markets = max(1, len({market_by_token.get(snapshot.token_id, snapshot.token_id) for snapshot in snapshots}))
    for snapshot in snapshots:
        p_hat = baseline_probability(snapshot)
        if p_hat is None:
            continue
        score = score_market(snapshot, p_hat, settings.MODEL_SIGMA_DEFAULT, settings, n_markets)
        raw_edge = score.buy_raw_edge if score.action == "BUY" else score.sell_raw_edge if score.action == "SELL" else score.best_net_edge
        row = EdgeSnapshot(
            market_id=market_by_token.get(snapshot.token_id),
            token_id=snapshot.token_id,
            side=score.side,
            p_hat=score.p_hat,
            sigma_p=score.sigma,
            bid=score.bid,
            ask=score.ask,
            raw_edge=raw_edge,
            total_cost=score.total_cost,
            net_edge=score.best_net_edge,
            kelly_size=score.kelly_size,
            action=score.action,
            raw_json=score.to_dict(),
        )
        session.add(row)
        saved += 1
        if score.action != "NONE":
            actionable += 1
        if include_all or score.action != "NONE":
            _print_json(score.to_dict())
    return {"snapshots_scored": len(snapshots), "edge_rows_saved": saved, "actionable": actionable}


async def _poll_loop(interval: int) -> None:
    from polymarket_edge.db.session import make_session_factory

    await poll_orderbooks_loop(make_session_factory(), interval=interval)


def _run_dashboard() -> int:
    app_path = Path(__file__).resolve().parent / "dashboard" / "app.py"
    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    env.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        "127.0.0.1",
        "--browser.gatherUsageStats",
        "false",
        "--server.headless",
        "true",
    ]
    return subprocess.call(cmd, env=env)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polymarket_edge.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db")
    p_discover = sub.add_parser("discover-markets")
    p_discover.add_argument("--max-events", type=int, default=None)

    p_poll = sub.add_parser("poll-orderbooks")
    p_poll.add_argument("--once", action="store_true")
    p_poll.add_argument("--loop", action="store_true")
    p_poll.add_argument("--interval", type=int, default=30)

    p_stream = sub.add_parser("stream-orderbooks")
    p_stream.add_argument("--max-tokens", type=int, default=200)

    p_trades = sub.add_parser("ingest-trades")
    p_trades.add_argument("--limit", type=int, default=500)

    p_edges = sub.add_parser("scan-edges")
    p_edges.add_argument("--latest", action="store_true")
    p_edges.add_argument("--all", action="store_true")

    sub.add_parser("scan-binary-arb")
    sub.add_parser("scan-logical-arb")

    p_paper = sub.add_parser("paper-trade")
    p_paper.add_argument("--from-latest-edges", action="store_true")

    p_backtest = sub.add_parser("backtest")
    p_backtest.add_argument("--holding-period", type=int, default=3600)

    sub.add_parser("promotion-check")
    sub.add_parser("setup-secrets")
    sub.add_parser("check-secrets")
    sub.add_parser("derive-api-creds")
    sub.add_parser("auth-check")
    sub.add_parser("balances")
    sub.add_parser("open-orders")
    sub.add_parser("cancel-all")
    sub.add_parser("live-preflight")

    p_live = sub.add_parser("live-tiny")
    p_live.add_argument("--once", action="store_true")
    p_live.add_argument("--loop", action="store_true")

    sub.add_parser("kill-switch")
    sub.add_parser("disable-live")
    sub.add_parser("reset-live-halt")
    sub.add_parser("dashboard")
    sub.add_parser("stream-user")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    reload_settings()

    if args.command == "init-db":
        init_db()
        print("database initialized")
        return 0

    if args.command == "dashboard":
        return _run_dashboard()

    if args.command == "poll-orderbooks" and args.loop:
        asyncio.run(_poll_loop(args.interval))
        return 0

    if args.command == "stream-orderbooks":
        _print_json(asdict(asyncio.run(stream_orderbooks(max_tokens=args.max_tokens))))
        return 0

    if args.command == "stream-user":
        print(asyncio.run(stream_user()))
        return 0

    if args.command == "setup-secrets":
        _print_json(setup_secrets())
        return 0

    if args.command == "check-secrets":
        _print_json(redacted_secret_status())
        return 0

    if args.command == "derive-api-creds":
        ok, message = derive_api_credentials()
        print(message)
        return 0 if ok else 2

    if args.command == "auth-check":
        result = auth_check()
        print(result.message)
        return 0 if result.ok else 2

    if args.command == "balances":
        ok, message = balances()
        print(message)
        return 0 if ok else 2

    if args.command == "open-orders":
        ok, message = open_orders()
        print(message)
        return 0 if ok else 2

    if args.command == "cancel-all":
        ok, message = cancel_all(dry_run=True)
        print(message)
        return 0 if ok else 2

    if args.command == "disable-live":
        disable_live()
        print("live trading disabled")
        return 0

    if args.command == "reset-live-halt":
        if sys.stdin.isatty():
            confirm = input("Type RESET LIVE HALT to continue: ")
        else:
            confirm = ""
        ok = reset_live_halt(confirm)
        print("live halt reset" if ok else "reset refused")
        return 0 if ok else 2

    with get_session() as session:
        if args.command == "discover-markets":
            summary = asyncio.run(discover_markets(session, max_events=args.max_events))
            _print_json(asdict(summary))
            return 0

        if args.command == "poll-orderbooks":
            if not args.once:
                print("pass --once or --loop")
                return 2
            summary = asyncio.run(poll_orderbooks_once(session))
            _print_json(asdict(summary))
            return 0

        if args.command == "ingest-trades":
            summary = asyncio.run(ingest_trades(session, limit=args.limit))
            _print_json(asdict(summary))
            return 0

        if args.command == "scan-edges":
            if not args.latest:
                print("only --latest is supported")
                return 2
            _print_json(_scan_edges_latest(session, include_all=args.all))
            return 0

        if args.command == "scan-binary-arb":
            arbs = [arb.to_dict() for arb in scan_binary_arbitrage(session)]
            _print_json({"count": len(arbs), "arbitrage": arbs})
            return 0

        if args.command == "scan-logical-arb":
            candidates = [candidate.to_dict() for candidate in scan_logical_arbitrage(session)]
            locked = sum(1 for c in candidates if c["arb_type"] == "LOCKED")
            _print_json({"count": len(candidates), "locked": locked, "candidates": candidates})
            return 0

        if args.command == "paper-trade":
            if not args.from_latest_edges:
                print("pass --from-latest-edges")
                return 2
            summary = paper_trade_from_latest_edges(session)
            _print_json(asdict(summary))
            return 0

        if args.command == "backtest":
            result = run_backtest(session, holding_period_seconds=args.holding_period)
            _print_json(result.to_dict())
            return 0

        if args.command == "promotion-check":
            result = run_backtest(session, holding_period_seconds=3600)
            settings = get_settings()
            checks = {
                "paper_trades": result.trades >= settings.MIN_PAPER_TRADES_BEFORE_LIVE,
                "win_rate": result.win_rate >= settings.MIN_PAPER_WIN_RATE,
                "average_net_edge": result.average_net_edge >= settings.MIN_PAPER_AVG_EDGE,
                "realised_pnl": result.total_pnl >= settings.MIN_PAPER_REALIZED_PNL,
                "edge_to_pnl_correlation": result.edge_to_pnl_correlation >= settings.MIN_PAPER_EDGE_PNL_CORRELATION,
            }
            _print_json({"passed": all(checks.values()), "checks": checks, "metrics": result.to_dict()})
            return 0 if all(checks.values()) else 2

        if args.command == "live-preflight":
            checks = [check.to_dict() for check in live_preflight(session)]
            passed = all(check["ok"] for check in checks)
            _print_json({"passed": passed, "checks": checks})
            return 0 if passed else 2

        if args.command == "live-tiny":
            settings = get_settings()
            if args.loop and not settings.ALLOW_LIVE_LOOP:
                print("live loop blocked: ALLOW_LIVE_LOOP is false")
                return 2
            checks = live_preflight(session)
            if not all(check.ok for check in checks):
                _print_json({"placed_order": False, "reason": "live-preflight failed", "checks": [c.to_dict() for c in checks]})
                return 2
            print("No live order placed: order submission requires the authenticated trading client and manual confirmation.")
            return 2

        if args.command == "kill-switch":
            trigger_kill_switch(session)
            print("kill switch triggered; live trading halted and cancel-all dry-run recorded")
            return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
