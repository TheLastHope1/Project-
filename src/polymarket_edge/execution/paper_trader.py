from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from polymarket_edge.config import Settings, get_settings
from polymarket_edge.db.models import AccountSnapshot, EdgeSnapshot, OrderbookSnapshot, PaperOrder, PaperPosition


@dataclass
class PaperTradeSummary:
    edges_considered: int = 0
    orders_created: int = 0
    filled: int = 0
    skipped_already_papered: int = 0
    skipped_no_book: int = 0
    skipped_no_cash: int = 0
    skipped_no_position: int = 0
    skipped_risk_limit: int = 0
    wallet_cash: float = 0.0
    wallet_equity: float = 0.0
    open_positions: int = 0


@dataclass(frozen=True)
class FillSimulation:
    size: float
    vwap: float | None
    limit_price: float | None
    notional: float
    slippage: float | None


@dataclass
class PaperWalletStatus:
    starting_cash: float
    cash_balance: float
    equity: float
    open_exposure: float
    realised_pnl: float
    unrealised_pnl: float
    positions_count: int
    orders_count: int
    last_snapshot_id: int | None
    positions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _latest_books(session: Session) -> dict[str, OrderbookSnapshot]:
    subq = (
        select(OrderbookSnapshot.token_id, func.max(OrderbookSnapshot.timestamp).label("max_ts"))
        .group_by(OrderbookSnapshot.token_id)
        .subquery()
    )
    rows = session.execute(
        select(OrderbookSnapshot)
        .join(subq, (OrderbookSnapshot.token_id == subq.c.token_id) & (OrderbookSnapshot.timestamp == subq.c.max_ts))
    ).scalars()
    return {row.token_id: row for row in rows}


def _latest_actionable_edges(session: Session) -> list[EdgeSnapshot]:
    rows = session.execute(
        select(EdgeSnapshot)
        .where(EdgeSnapshot.action.in_(("BUY", "SELL")), EdgeSnapshot.net_edge > 0)
        .order_by(desc(EdgeSnapshot.timestamp), desc(EdgeSnapshot.id))
    ).scalars()
    out: list[EdgeSnapshot] = []
    seen: set[str] = set()
    for row in rows:
        if row.token_id in seen:
            continue
        seen.add(row.token_id)
        out.append(row)
    return out


def _papered_edge_ids(session: Session) -> set[int]:
    ids: set[int] = set()
    for raw_json in session.execute(select(PaperOrder.raw_json)).scalars():
        if not isinstance(raw_json, dict):
            continue
        try:
            edge_id = int(raw_json.get("edge_snapshot_id"))
        except (TypeError, ValueError):
            continue
        ids.add(edge_id)
    return ids


def _positions_by_token(session: Session) -> dict[str, PaperPosition]:
    return {
        position.token_id: position
        for position in session.execute(select(PaperPosition)).scalars()
    }


def _latest_account_snapshot(session: Session) -> AccountSnapshot | None:
    return session.execute(
        select(AccountSnapshot).order_by(desc(AccountSnapshot.created_at), desc(AccountSnapshot.id)).limit(1)
    ).scalar_one_or_none()


def _snapshot_starting_cash(snapshot: AccountSnapshot, settings: Settings) -> float:
    raw = snapshot.raw_json or {}
    try:
        return float(raw.get("starting_cash", settings.PAPER_STARTING_CASH_USD))
    except (TypeError, ValueError):
        return settings.PAPER_STARTING_CASH_USD


def ensure_paper_wallet(
    session: Session,
    settings: Settings | None = None,
    starting_cash: float | None = None,
) -> AccountSnapshot:
    settings = settings or get_settings()
    latest = _latest_account_snapshot(session)
    if latest is not None:
        return latest
    initial_cash = settings.PAPER_STARTING_CASH_USD if starting_cash is None else max(0.0, float(starting_cash))
    snapshot = AccountSnapshot(
        cash_balance=initial_cash,
        open_exposure=0.0,
        realised_pnl=0.0,
        unrealised_pnl=0.0,
        raw_json={
            "wallet_type": "paper",
            "starting_cash": initial_cash,
            "equity": initial_cash,
        },
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _mark_price(book: OrderbookSnapshot | None) -> float | None:
    if book is None:
        return None
    if book.best_bid is not None:
        return float(book.best_bid)
    if book.mid is not None:
        return float(book.mid)
    return None


def _build_paper_wallet_status(
    session: Session,
    settings: Settings | None = None,
    *,
    persist: bool,
) -> PaperWalletStatus:
    settings = settings or get_settings()
    latest = ensure_paper_wallet(session, settings)
    starting_cash = _snapshot_starting_cash(latest, settings)
    cash = float(latest.cash_balance or 0.0)
    books = _latest_books(session)
    positions = list(session.execute(select(PaperPosition)).scalars())

    realised = 0.0
    unrealised = 0.0
    open_exposure = 0.0
    position_rows: list[dict[str, Any]] = []
    for position in positions:
        realised += float(position.realised_pnl or 0.0)
        if position.shares <= 0:
            continue
        mark = _mark_price(books.get(position.token_id))
        market_value = float(position.shares) * mark if mark is not None else 0.0
        pnl = market_value - float(position.cost_basis or 0.0)
        open_exposure += market_value
        unrealised += pnl
        position_rows.append(
            {
                "market_id": position.market_id,
                "token_id": position.token_id,
                "shares": position.shares,
                "avg_price": position.avg_price,
                "cost_basis": position.cost_basis,
                "mark_price": mark,
                "market_value": market_value,
                "unrealised_pnl": pnl,
            }
        )

    equity = cash + open_exposure
    snapshot_id = latest.id
    if persist:
        snapshot = AccountSnapshot(
            cash_balance=cash,
            open_exposure=open_exposure,
            realised_pnl=realised,
            unrealised_pnl=unrealised,
            raw_json={
                "wallet_type": "paper",
                "starting_cash": starting_cash,
                "equity": equity,
                "positions": position_rows,
            },
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
    return PaperWalletStatus(
        starting_cash=starting_cash,
        cash_balance=cash,
        equity=equity,
        open_exposure=open_exposure,
        realised_pnl=realised,
        unrealised_pnl=unrealised,
        positions_count=len(position_rows),
        orders_count=session.scalar(select(func.count()).select_from(PaperOrder)) or 0,
        last_snapshot_id=snapshot_id,
        positions=position_rows,
    )


def record_paper_wallet_snapshot(session: Session, settings: Settings | None = None) -> PaperWalletStatus:
    return _build_paper_wallet_status(session, settings, persist=True)


def paper_wallet_status(session: Session, settings: Settings | None = None) -> PaperWalletStatus:
    return _build_paper_wallet_status(session, settings, persist=False)


def reset_paper_wallet(session: Session, starting_cash: float | None = None) -> PaperWalletStatus:
    settings = get_settings()
    session.execute(delete(PaperOrder))
    session.execute(delete(PaperPosition))
    session.execute(delete(AccountSnapshot))
    session.flush()
    ensure_paper_wallet(session, settings, starting_cash=starting_cash)
    return record_paper_wallet_snapshot(session, settings)


def _simulate_limit_fill(
    levels: list[dict[str, float]],
    target_size: float,
    best_price: float,
    side: str,
) -> FillSimulation:
    remaining = max(0.0, float(target_size))
    if remaining <= 0:
        return FillSimulation(0.0, None, None, 0.0, None)
    notional = 0.0
    filled = 0.0
    limit_price: float | None = None
    for level in levels:
        try:
            price = float(level.get("price", 0.0))
            available = float(level.get("size", 0.0))
        except (TypeError, ValueError):
            continue
        if price <= 0 or available <= 0:
            continue
        take = min(remaining, available)
        notional += take * price
        filled += take
        remaining -= take
        limit_price = price
        if remaining <= 0:
            break
    if filled <= 0:
        return FillSimulation(0.0, None, None, 0.0, None)
    vwap = notional / filled
    slippage = vwap - best_price if side == "BUY" else best_price - vwap
    return FillSimulation(filled, vwap, limit_price, notional, slippage)


def _target_notional(edge: EdgeSnapshot, cash: float, settings: Settings) -> float:
    if cash <= 0:
        return 0.0
    kelly_fraction = max(0.0, min(float(edge.kelly_size or 0.0), settings.PAPER_MAX_POSITION_FRACTION))
    if kelly_fraction <= 0:
        kelly_fraction = settings.PAPER_DEFAULT_POSITION_FRACTION
    return min(
        settings.PAPER_MAX_ORDER_USD,
        cash * settings.PAPER_MAX_POSITION_FRACTION,
        cash * kelly_fraction,
    )


def _position_market_exposure(position: PaperPosition | None) -> float:
    if position is None or position.shares <= 0:
        return 0.0
    return float(position.cost_basis or 0.0)


def _apply_buy(
    session: Session,
    edge: EdgeSnapshot,
    book: OrderbookSnapshot,
    position: PaperPosition | None,
    cash: float,
    settings: Settings,
    starting_cash: float,
) -> tuple[PaperOrder | None, PaperPosition | None, float, str | None]:
    if book.best_ask is None or book.best_ask <= 0:
        return None, position, cash, "no_book"

    max_market_exposure = starting_cash * settings.PAPER_MAX_POSITION_FRACTION
    remaining_market_exposure = max(0.0, max_market_exposure - _position_market_exposure(position))
    target_notional = min(_target_notional(edge, cash, settings), remaining_market_exposure, cash)
    if target_notional < settings.PAPER_MIN_ORDER_USD:
        return None, position, cash, "risk_limit" if remaining_market_exposure <= 0 else "no_cash"

    target_size = target_notional / float(book.best_ask)
    fill = _simulate_limit_fill(book.ask_depth, target_size, float(book.best_ask), "BUY")
    if fill.vwap is None or fill.limit_price is None or fill.notional < settings.PAPER_MIN_ORDER_USD:
        return None, position, cash, "no_book"
    if fill.notional > cash:
        return None, position, cash, "no_cash"

    if position is None:
        position = PaperPosition(
            market_id=edge.market_id,
            token_id=edge.token_id,
            shares=0.0,
            avg_price=0.0,
            cost_basis=0.0,
            realised_pnl=0.0,
            raw_json={},
        )
        session.add(position)

    new_shares = float(position.shares or 0.0) + fill.size
    new_cost_basis = float(position.cost_basis or 0.0) + fill.notional
    position.market_id = edge.market_id
    position.shares = new_shares
    position.cost_basis = new_cost_basis
    position.avg_price = new_cost_basis / new_shares if new_shares > 0 else 0.0
    position.raw_json = {
        **(position.raw_json or {}),
        "last_buy_edge_snapshot_id": edge.id,
        "last_buy_vwap": fill.vwap,
    }
    cash -= fill.notional
    order = PaperOrder(
        market_id=edge.market_id,
        token_id=edge.token_id,
        side="BUY",
        limit_price=fill.limit_price,
        size=fill.size,
        edge_score=edge.net_edge,
        status="filled",
        simulated_fill_price=fill.vwap,
        simulated_pnl=0.0,
        raw_json={
            "edge_snapshot_id": edge.id,
            "paper_wallet": True,
            "order_type": "limit",
            "notional": fill.notional,
            "slippage": fill.slippage,
            "cash_after": cash,
        },
    )
    session.add(order)
    return order, position, cash, None


def _apply_sell(
    session: Session,
    edge: EdgeSnapshot,
    book: OrderbookSnapshot,
    position: PaperPosition | None,
    cash: float,
    settings: Settings,
) -> tuple[PaperOrder | None, PaperPosition | None, float, str | None]:
    if position is None or position.shares <= 0:
        return None, position, cash, "no_position"
    if book.best_bid is None or book.best_bid <= 0:
        return None, position, cash, "no_book"

    target_notional = min(_target_notional(edge, max(cash, settings.PAPER_MIN_ORDER_USD), settings), position.shares * book.best_bid)
    if target_notional < settings.PAPER_MIN_ORDER_USD:
        return None, position, cash, "risk_limit"

    target_size = min(position.shares, target_notional / float(book.best_bid))
    fill = _simulate_limit_fill(book.bid_depth, target_size, float(book.best_bid), "SELL")
    if fill.vwap is None or fill.limit_price is None or fill.notional < settings.PAPER_MIN_ORDER_USD:
        return None, position, cash, "no_book"

    avg_price = float(position.avg_price or 0.0)
    realised = (fill.vwap - avg_price) * fill.size
    cash += fill.notional
    remaining_shares = max(0.0, float(position.shares or 0.0) - fill.size)
    position.shares = remaining_shares
    position.cost_basis = avg_price * remaining_shares
    position.realised_pnl = float(position.realised_pnl or 0.0) + realised
    if remaining_shares <= 1e-9:
        position.shares = 0.0
        position.avg_price = 0.0
        position.cost_basis = 0.0
    position.raw_json = {
        **(position.raw_json or {}),
        "last_sell_edge_snapshot_id": edge.id,
        "last_sell_vwap": fill.vwap,
    }
    order = PaperOrder(
        market_id=edge.market_id,
        token_id=edge.token_id,
        side="SELL",
        limit_price=fill.limit_price,
        size=fill.size,
        edge_score=edge.net_edge,
        status="filled",
        simulated_fill_price=fill.vwap,
        simulated_pnl=realised,
        raw_json={
            "edge_snapshot_id": edge.id,
            "paper_wallet": True,
            "order_type": "limit",
            "notional": fill.notional,
            "slippage": fill.slippage,
            "cash_after": cash,
        },
    )
    session.add(order)
    return order, position, cash, None


def _record_cash_snapshot(session: Session, cash: float, settings: Settings) -> None:
    latest = ensure_paper_wallet(session, settings)
    starting_cash = _snapshot_starting_cash(latest, settings)
    latest.cash_balance = cash
    latest.raw_json = {
        **(latest.raw_json or {}),
        "wallet_type": "paper",
        "starting_cash": starting_cash,
        "cash_balance": cash,
    }


def paper_trade_from_latest_edges(session: Session) -> PaperTradeSummary:
    settings = get_settings()
    latest = ensure_paper_wallet(session, settings)
    starting_cash = _snapshot_starting_cash(latest, settings)
    cash = float(latest.cash_balance or 0.0)
    books = _latest_books(session)
    positions = _positions_by_token(session)
    papered_edge_ids = _papered_edge_ids(session)
    edges = _latest_actionable_edges(session)
    summary = PaperTradeSummary(edges_considered=len(edges), wallet_cash=cash, wallet_equity=cash)

    for edge in edges:
        if edge.id in papered_edge_ids:
            summary.skipped_already_papered += 1
            continue
        book = books.get(edge.token_id)
        if book is None:
            summary.skipped_no_book += 1
            continue
        position = positions.get(edge.token_id)
        if edge.action == "BUY":
            order, position, cash, skip = _apply_buy(session, edge, book, position, cash, settings, starting_cash)
        elif edge.action == "SELL":
            order, position, cash, skip = _apply_sell(session, edge, book, position, cash, settings)
        else:
            continue

        if skip == "no_book":
            summary.skipped_no_book += 1
            continue
        if skip == "no_cash":
            summary.skipped_no_cash += 1
            continue
        if skip == "no_position":
            summary.skipped_no_position += 1
            continue
        if skip == "risk_limit":
            summary.skipped_risk_limit += 1
            continue
        if order is None:
            continue
        if position is not None:
            positions[position.token_id] = position
        papered_edge_ids.add(edge.id)
        summary.orders_created += 1
        summary.filled += 1
        _record_cash_snapshot(session, cash, settings)

    _record_cash_snapshot(session, cash, settings)
    wallet = record_paper_wallet_snapshot(session, settings)
    summary.wallet_cash = wallet.cash_balance
    summary.wallet_equity = wallet.equity
    summary.open_positions = wallet.positions_count
    return summary
