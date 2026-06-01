from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from polymarket_edge.arbitrage.binary_scanner import scan_binary_arbitrage
from polymarket_edge.db.models import Base, EdgeSnapshot, Market, OrderbookSnapshot, PaperPosition, Token
from polymarket_edge.db.session import make_engine
from polymarket_edge.execution.paper_trader import paper_trade_from_latest_edges, paper_wallet_status


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'edge.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _binary_fixture(session, yes_ask=0.49, no_ask=0.49, yes_bid=0.48, no_bid=0.48):
    session.add(Market(market_id="m1", active=True, closed=False, raw_json={}))
    session.add_all(
        [
            Token(token_id="yes", market_id="m1", outcome="YES", outcome_index=0, raw_json={}),
            Token(token_id="no", market_id="m1", outcome="NO", outcome_index=1, raw_json={}),
        ]
    )
    now = datetime.now(UTC)
    session.add_all(
        [
            OrderbookSnapshot(
                token_id="yes",
                timestamp=now,
                best_bid=yes_bid,
                best_ask=yes_ask,
                mid=(yes_bid + yes_ask) / 2,
                spread=yes_ask - yes_bid,
                bid_depth=[{"price": yes_bid, "size": 10}],
                ask_depth=[{"price": yes_ask, "size": 10}],
                raw_json={},
            ),
            OrderbookSnapshot(
                token_id="no",
                timestamp=now,
                best_bid=no_bid,
                best_ask=no_ask,
                mid=(no_bid + no_ask) / 2,
                spread=no_ask - no_bid,
                bid_depth=[{"price": no_bid, "size": 10}],
                ask_depth=[{"price": no_ask, "size": 10}],
                raw_json={},
            ),
        ]
    )
    session.commit()


def test_binary_long_arbitrage(tmp_path):
    session = _session(tmp_path)
    _binary_fixture(session, yes_ask=0.49, no_ask=0.49)
    arbs = scan_binary_arbitrage(session)
    assert len(arbs) == 1
    assert arbs[0].side == "LONG"


def test_binary_short_arbitrage(tmp_path):
    session = _session(tmp_path)
    _binary_fixture(session, yes_bid=0.51, no_bid=0.51)
    arbs = scan_binary_arbitrage(session)
    assert any(arb.side == "SHORT" for arb in arbs)


def test_binary_no_arbitrage(tmp_path):
    session = _session(tmp_path)
    _binary_fixture(session, yes_ask=0.51, no_ask=0.51, yes_bid=0.49, no_bid=0.49)
    assert scan_binary_arbitrage(session) == []


def test_paper_order_creation_and_fill(tmp_path):
    session = _session(tmp_path)
    _binary_fixture(session)
    edge = EdgeSnapshot(
        market_id="m1",
        token_id="yes",
        timestamp=datetime.now(UTC),
        side="BUY",
        p_hat=0.7,
        sigma_p=0.01,
        bid=0.48,
        ask=0.49,
        raw_edge=0.21,
        total_cost=0.01,
        net_edge=0.2,
        kelly_size=0.01,
        action="BUY",
        raw_json={},
    )
    session.add(edge)
    session.commit()
    summary = paper_trade_from_latest_edges(session)
    assert summary.orders_created == 1
    assert summary.filled == 1
    wallet = paper_wallet_status(session)
    position = session.query(PaperPosition).filter_by(token_id="yes").one()
    assert wallet.cash_balance < 1000
    assert wallet.positions_count == 1
    assert position.shares > 0
    assert position.cost_basis > 0


def test_paper_wallet_does_not_short_sell_without_position(tmp_path):
    session = _session(tmp_path)
    _binary_fixture(session)
    session.add(
        EdgeSnapshot(
            market_id="m1",
            token_id="yes",
            timestamp=datetime.now(UTC),
            side="SELL",
            p_hat=0.2,
            sigma_p=0.01,
            bid=0.48,
            ask=0.49,
            raw_edge=0.28,
            total_cost=0.01,
            net_edge=0.27,
            kelly_size=0.01,
            action="SELL",
            raw_json={},
        )
    )
    session.commit()

    summary = paper_trade_from_latest_edges(session)

    assert summary.orders_created == 0
    assert summary.skipped_no_position == 1
    assert session.query(PaperPosition).count() == 0


def test_backtest_fixture_has_later_snapshot(tmp_path):
    session = _session(tmp_path)
    session.add(Market(market_id="m1", active=True, closed=False, raw_json={}))
    session.add(Token(token_id="yes", market_id="m1", outcome="YES", outcome_index=0, raw_json={}))
    start = datetime.now(UTC)
    session.add_all(
        [
            OrderbookSnapshot(token_id="yes", timestamp=start, best_bid=0.48, best_ask=0.5, mid=0.49, spread=0.02, bid_depth=[], ask_depth=[], raw_json={}),
            OrderbookSnapshot(token_id="yes", timestamp=start + timedelta(seconds=3600), best_bid=0.53, best_ask=0.55, mid=0.54, spread=0.02, bid_depth=[], ask_depth=[], raw_json={}),
            EdgeSnapshot(market_id="m1", token_id="yes", timestamp=start, side="BUY", p_hat=0.7, sigma_p=0.01, bid=0.48, ask=0.5, raw_edge=0.2, total_cost=0.01, net_edge=0.19, kelly_size=1.0, action="BUY", raw_json={}),
        ]
    )
    session.commit()
    from polymarket_edge.backtest.backtester import run_backtest

    result = run_backtest(session, 3600)
    assert result.trades == 1
    assert result.total_pnl > 0
