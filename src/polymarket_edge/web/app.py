from __future__ import annotations

import asyncio
import html
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from polymarket_edge.arbitrage.binary_scanner import scan_binary_arbitrage
from polymarket_edge.backtest.backtester import run_backtest
from polymarket_edge.config import get_settings
from polymarket_edge.db.models import EdgeSnapshot, Market, OrderbookSnapshot, PaperOrder, Token
from polymarket_edge.db.session import get_session, init_db
from polymarket_edge.execution.paper_trader import paper_trade_from_latest_edges
from polymarket_edge.ingestion.market_discovery import discover_markets
from polymarket_edge.ingestion.orderbook_poller import poll_orderbooks_once
from polymarket_edge.trading.kill_switch import trigger_kill_switch
from polymarket_edge.trading.preflight import live_preflight


def _session_dep():
    with get_session() as session:
        yield session


SessionDep = Annotated[Session, Depends(_session_dep)]


def _admin_auth(
    authorization: Annotated[str | None, Header()] = None,
    x_api_token: Annotated[str | None, Header(alias="x-api-token")] = None,
    token: Annotated[str | None, Query()] = None,
) -> None:
    configured = get_settings().POLYMARKET_EDGE_API_TOKEN
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin API disabled until POLYMARKET_EDGE_API_TOKEN is set.",
        )
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    supplied = bearer or x_api_token or token
    if supplied != configured:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


AdminAuth = Annotated[None, Depends(_admin_auth)]


def _status(session: Session) -> dict[str, Any]:
    try:
        latest_snapshot = session.scalar(select(func.max(OrderbookSnapshot.timestamp)))
        active_markets = session.scalar(select(func.count()).select_from(Market).where(Market.active.is_(True))) or 0
        active_tokens = session.scalar(select(func.count()).select_from(Token)) or 0
        orderbook_snapshots = session.scalar(select(func.count()).select_from(OrderbookSnapshot)) or 0
        edge_snapshots = session.scalar(select(func.count()).select_from(EdgeSnapshot)) or 0
        paper_orders = session.scalar(select(func.count()).select_from(PaperOrder)) or 0
        database_initialized = True
        database_error = None
    except SQLAlchemyError as exc:
        session.rollback()
        latest_snapshot = None
        active_markets = 0
        active_tokens = 0
        orderbook_snapshots = 0
        edge_snapshots = 0
        paper_orders = 0
        database_initialized = False
        database_error = exc.__class__.__name__
    return {
        "database_initialized": database_initialized,
        "database_error": database_error,
        "active_markets": active_markets,
        "active_tokens": active_tokens,
        "orderbook_snapshots": orderbook_snapshots,
        "edge_snapshots": edge_snapshots,
        "paper_orders": paper_orders,
        "latest_snapshot": latest_snapshot.isoformat() if latest_snapshot else None,
        "trading_mode": get_settings().TRADING_MODE,
        "live_trading_enabled": get_settings().LIVE_TRADING_ENABLED,
        "real_money_acknowledged": get_settings().REAL_MONEY_ACKNOWLEDGED,
        "live_trading_halted": get_settings().LIVE_TRADING_HALTED,
    }


def _top_edges(session: Session, action: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    stmt = select(EdgeSnapshot).order_by(EdgeSnapshot.net_edge.desc().nullslast()).limit(max(1, min(limit, 200)))
    if action:
        stmt = stmt.where(EdgeSnapshot.action == action.upper())
    return [
        {
            "id": row.id,
            "timestamp": row.timestamp,
            "market_id": row.market_id,
            "token_id": row.token_id,
            "action": row.action,
            "side": row.side,
            "bid": row.bid,
            "ask": row.ask,
            "p_hat": row.p_hat,
            "sigma_p": row.sigma_p,
            "net_edge": row.net_edge,
            "kelly_size": row.kelly_size,
        }
        for row in session.execute(stmt).scalars()
    ]


def _paper_orders(session: Session, limit: int = 50) -> list[dict[str, Any]]:
    rows = session.execute(
        select(PaperOrder).order_by(PaperOrder.created_at.desc()).limit(max(1, min(limit, 200)))
    ).scalars()
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "market_id": row.market_id,
            "token_id": row.token_id,
            "side": row.side,
            "limit_price": row.limit_price,
            "size": row.size,
            "status": row.status,
            "simulated_fill_price": row.simulated_fill_price,
            "simulated_pnl": row.simulated_pnl,
        }
        for row in rows
    ]


def _scan_edges_latest(session: Session) -> dict[str, int]:
    # Import lazily to avoid CLI startup side effects in the web process.
    from polymarket_edge.cli import _scan_edges_latest as scan_edges_latest

    return scan_edges_latest(session, include_all=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Polymarket Edge", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index(session: SessionDep) -> str:
        status = _status(session)
        edges = _top_edges(session, limit=10) if status["database_initialized"] else []
        rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(str(row['action']))}</td>"
            f"<td>{html.escape(str(row['market_id']))}</td>"
            f"<td>{html.escape(str(row['token_id']))}</td>"
            f"<td>{row['bid']}</td><td>{row['ask']}</td><td>{row['net_edge']}</td>"
            "</tr>"
            for row in edges
        )
        return f"""
        <!doctype html>
        <html>
          <head>
            <title>Polymarket Edge</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <style>
              body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #111827; }}
              .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
              .metric {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; }}
              .label {{ color: #6b7280; font-size: 12px; text-transform: uppercase; }}
              .value {{ font-size: 24px; font-weight: 650; }}
              table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
              th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; font-size: 13px; }}
              code {{ background: #f3f4f6; padding: 2px 4px; border-radius: 4px; }}
            </style>
          </head>
          <body>
            <h1>Polymarket Edge</h1>
            <div class="metrics">
              <div class="metric"><div class="label">Active markets</div><div class="value">{status["active_markets"]}</div></div>
              <div class="metric"><div class="label">Active tokens</div><div class="value">{status["active_tokens"]}</div></div>
              <div class="metric"><div class="label">Snapshots</div><div class="value">{status["orderbook_snapshots"]}</div></div>
              <div class="metric"><div class="label">Paper orders</div><div class="value">{status["paper_orders"]}</div></div>
            </div>
            <p>Mode: <code>{html.escape(str(status["trading_mode"]))}</code>.
            Live enabled: <code>{status["live_trading_enabled"]}</code>.
            Latest snapshot: <code>{html.escape(str(status["latest_snapshot"]))}</code>.</p>
            <h2>Top Edges</h2>
            <table>
              <thead><tr><th>Action</th><th>Market</th><th>Token</th><th>Bid</th><th>Ask</th><th>Net edge</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </body>
        </html>
        """

    @app.get("/health")
    def health(session: SessionDep) -> dict[str, Any]:
        session.execute(text("SELECT 1"))
        return {"ok": True}

    @app.get("/api/status")
    def api_status(session: SessionDep) -> dict[str, Any]:
        return _status(session)

    @app.get("/api/edges")
    def api_edges(session: SessionDep, action: str | None = None, limit: int = 50) -> dict[str, Any]:
        return {"edges": _top_edges(session, action=action, limit=limit)}

    @app.get("/api/binary-arb")
    def api_binary_arb(session: SessionDep) -> dict[str, Any]:
        arbs = [arb.to_dict() for arb in scan_binary_arbitrage(session)]
        return {"count": len(arbs), "arbitrage": arbs}

    @app.get("/api/paper-orders")
    def api_paper_orders(session: SessionDep, limit: int = 50) -> dict[str, Any]:
        return {"orders": _paper_orders(session, limit=limit)}

    @app.get("/api/live-preflight")
    def api_live_preflight(session: SessionDep) -> dict[str, Any]:
        checks = [check.to_dict() for check in live_preflight(session)]
        return {"passed": all(check["ok"] for check in checks), "checks": checks}

    @app.post("/api/admin/init-db")
    def api_init_db(_: AdminAuth) -> dict[str, Any]:
        init_db()
        return {"ok": True}

    @app.post("/api/admin/discover-markets")
    def api_discover_markets(session: SessionDep, _: AdminAuth, max_events: int = 100) -> dict[str, Any]:
        capped = max(1, min(max_events, 500))
        summary = asyncio.run(discover_markets(session, max_events=capped))
        return {"requested_max_events": capped, **summary.__dict__}

    @app.post("/api/admin/poll-orderbooks")
    def api_poll_orderbooks(session: SessionDep, _: AdminAuth, max_tokens: int = 250) -> dict[str, Any]:
        capped = max(1, min(max_tokens, 1000))
        summary = asyncio.run(poll_orderbooks_once(session, max_tokens=capped))
        return {"requested_max_tokens": capped, **summary.__dict__}

    @app.post("/api/admin/scan-edges")
    def api_scan_edges(session: SessionDep, _: AdminAuth) -> dict[str, Any]:
        return _scan_edges_latest(session)

    @app.post("/api/admin/paper-trade")
    def api_paper_trade(session: SessionDep, _: AdminAuth) -> dict[str, Any]:
        return paper_trade_from_latest_edges(session).__dict__

    @app.post("/api/admin/backtest")
    def api_backtest(session: SessionDep, _: AdminAuth, holding_period: int = 3600) -> dict[str, Any]:
        return run_backtest(session, holding_period_seconds=holding_period).to_dict()

    @app.post("/api/admin/kill-switch")
    async def api_kill_switch(request: Request, session: SessionDep, _: AdminAuth) -> dict[str, Any]:
        payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        reason = str(payload.get("reason") or "dashboard kill switch")
        local_env_updated = trigger_kill_switch(session, reason=reason)
        return {"ok": True, "live_trading_halted": True, "local_env_updated": local_env_updated}

    return app


app = create_app()
