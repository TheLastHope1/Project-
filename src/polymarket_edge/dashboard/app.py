from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from polymarket_edge.arbitrage.binary_scanner import scan_binary_arbitrage
from polymarket_edge.config import get_settings
from polymarket_edge.db.models import EdgeSnapshot, Market, OrderbookSnapshot, PaperOrder, Token
from polymarket_edge.db.session import get_session


def _df(rows):
    return pd.DataFrame(rows)


st.set_page_config(page_title="Polymarket Edge", layout="wide")
st.title("Polymarket Edge")

settings = get_settings()

with get_session() as session:
    active_markets = session.scalar(select(func.count()).select_from(Market).where(Market.active.is_(True))) or 0
    active_tokens = session.scalar(select(func.count()).select_from(Token)) or 0
    latest_snapshot = session.scalar(select(func.max(OrderbookSnapshot.timestamp)))
    recent_snapshots = session.scalar(select(func.count()).select_from(OrderbookSnapshot)) or 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active markets", active_markets)
    c2.metric("Active tokens", active_tokens)
    c3.metric("Snapshots", recent_snapshots)
    c4.metric("Latest snapshot", str(latest_snapshot or "none"))

    st.subheader("Top buy edges")
    buy_rows = [
        {
            "market_id": row.market_id,
            "token_id": row.token_id,
            "bid": row.bid,
            "ask": row.ask,
            "p_hat": row.p_hat,
            "sigma": row.sigma_p,
            "total_cost": row.total_cost,
            "net_edge": row.net_edge,
            "kelly_size": row.kelly_size,
        }
        for row in session.execute(
            select(EdgeSnapshot)
            .where(EdgeSnapshot.action == "BUY")
            .order_by(EdgeSnapshot.net_edge.desc())
            .limit(50)
        ).scalars()
    ]
    st.dataframe(_df(buy_rows), use_container_width=True)

    st.subheader("Top sell edges")
    sell_rows = [
        {
            "market_id": row.market_id,
            "token_id": row.token_id,
            "bid": row.bid,
            "ask": row.ask,
            "p_hat": row.p_hat,
            "sigma": row.sigma_p,
            "total_cost": row.total_cost,
            "net_edge": row.net_edge,
            "kelly_size": row.kelly_size,
        }
        for row in session.execute(
            select(EdgeSnapshot)
            .where(EdgeSnapshot.action == "SELL")
            .order_by(EdgeSnapshot.net_edge.desc())
            .limit(50)
        ).scalars()
    ]
    st.dataframe(_df(sell_rows), use_container_width=True)

    st.subheader("Binary arbitrage")
    st.dataframe(_df([arb.to_dict() for arb in scan_binary_arbitrage(session)]), use_container_width=True)

    st.subheader("Paper trading")
    orders = [
        {
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
        for row in session.execute(select(PaperOrder).order_by(PaperOrder.created_at.desc()).limit(100)).scalars()
    ]
    st.dataframe(_df(orders), use_container_width=True)

st.subheader("Live risk")
st.json(
    {
        "TRADING_MODE": settings.TRADING_MODE,
        "LIVE_TRADING_ENABLED": settings.LIVE_TRADING_ENABLED,
        "REAL_MONEY_ACKNOWLEDGED": settings.REAL_MONEY_ACKNOWLEDGED,
        "LIVE_TRADING_HALTED": settings.LIVE_TRADING_HALTED,
        "MAX_ORDER_USD": settings.MAX_ORDER_USD,
        "MAX_DAILY_LOSS_USD": settings.MAX_DAILY_LOSS_USD,
        "MAX_OPEN_EXPOSURE_USD": settings.MAX_OPEN_EXPOSURE_USD,
        "MAX_MARKET_EXPOSURE_USD": settings.MAX_MARKET_EXPOSURE_USD,
    }
)

