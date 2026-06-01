from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from polymarket_edge.arbitrage.logical_scanner import (
    parse_direction,
    parse_threshold,
    scan_logical_arbitrage,
)
from polymarket_edge.db.models import Base, Market, OrderbookSnapshot, Token
from polymarket_edge.db.session import make_engine

END = datetime(2026, 12, 31, tzinfo=UTC)


def _session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'logic.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _add_threshold_market(
    session,
    market_id: str,
    question: str,
    yes_bid: float,
    yes_ask: float,
    *,
    event_id: str = "evt-btc-2026",
    end_date: datetime | None = END,
    depth: float = 100.0,
):
    """Add a threshold market with a YES token and one orderbook snapshot."""
    session.add(
        Market(
            market_id=market_id,
            event_id=event_id,
            question=question,
            active=True,
            closed=False,
            end_date=end_date,
            raw_json={},
        )
    )
    yes_token = f"{market_id}-yes"
    session.add(Token(token_id=yes_token, market_id=market_id, outcome="Yes", outcome_index=0, raw_json={}))
    session.add(Token(token_id=f"{market_id}-no", market_id=market_id, outcome="No", outcome_index=1, raw_json={}))
    session.add(
        OrderbookSnapshot(
            token_id=yes_token,
            timestamp=datetime.now(UTC),
            best_bid=yes_bid,
            best_ask=yes_ask,
            mid=(yes_bid + yes_ask) / 2,
            spread=yes_ask - yes_bid,
            bid_depth=[{"price": yes_bid, "size": depth}],
            ask_depth=[{"price": yes_ask, "size": depth}],
            raw_json={},
        )
    )


# ---- threshold + direction parsing --------------------------------------


def test_parse_threshold_variants():
    assert parse_threshold("Will Bitcoin reach $100,000 by 2026?") == 100000.0
    assert parse_threshold("Will BTC hit $120k in 2026?") == 120000.0
    assert parse_threshold("Will ETH reach $1.2m?") == 1_200_000.0
    assert parse_threshold("Will gold close above 2500 today?") == 2500.0
    assert parse_threshold("no numbers here") is None


def test_parse_threshold_skips_bare_year():
    # The $-marked amount must win over the bare year.
    assert parse_threshold("Will Bitcoin reach $90k by Dec 2026?") == 90000.0


def test_parse_threshold_rejects_bare_year():
    # Live-data regression: election markets carry a year but no level. The
    # year must NOT be read as a threshold, or unrelated markets get grouped.
    assert parse_threshold("Will Rick Caruso win the California Governor Election in 2026?") is None
    assert parse_threshold("Will the Democrats win in 2028?") is None
    # A real level alongside a year still resolves to the level.
    assert parse_threshold("Will Bitcoin hit $150k by December 31, 2026?") == 150000.0


def test_parse_direction():
    assert parse_direction("Will BTC reach $100k?") == "ABOVE"
    assert parse_direction("Will BTC be above $100k?") == "ABOVE"
    assert parse_direction("Will BTC stay below $80k?") == "BELOW"
    assert parse_direction("Will BTC be at most $80k?") == "BELOW"
    assert parse_direction("Who wins the election?") is None


def test_parse_direction_word_boundaries():
    # Live-data regression: "over" must not match inside "Governor", etc.
    assert parse_direction("Will Rick Caruso win the California Governor Election in 2026?") is None
    assert parse_direction("Will Whitman win the Senate race?") is None


# ---- locked arbitrage ----------------------------------------------------


def test_locked_arb_on_inverted_above_ladder(tmp_path):
    session = _session(tmp_path)
    # ABOVE ladder: P($100k) must be <= P($90k). Here the $100k YES is bid 0.60
    # while the $90k YES asks 0.50 -- inverted. Sell $100k YES, buy $90k YES.
    _add_threshold_market(session, "m100", "Will BTC reach $100k by 2026?", yes_bid=0.60, yes_ask=0.62)
    _add_threshold_market(session, "m90", "Will BTC reach $90k by 2026?", yes_bid=0.48, yes_ask=0.50)
    session.commit()

    arbs = scan_logical_arbitrage(session)
    locked = [a for a in arbs if a.arb_type == "LOCKED"]
    assert len(locked) == 1
    arb = locked[0]
    assert arb.strong_market_id == "m100"  # higher threshold = stronger
    assert arb.weak_market_id == "m90"
    # margin = strong_bid(0.60) - weak_ask(0.50) - fee(0) = 0.10
    assert abs(arb.margin - 0.10) < 1e-9
    assert arb.executable_size == 100.0
    assert abs(arb.estimated_profit - 10.0) < 1e-9
    assert arb.requires_review is False


def test_locked_arb_on_inverted_below_ladder(tmp_path):
    session = _session(tmp_path)
    # BELOW ladder: P(<=$80k) must be <= P(<=$90k). Stronger = lower threshold.
    # Invert it: the $80k YES bid (0.55) exceeds the $90k YES ask (0.50).
    _add_threshold_market(session, "b80", "Will BTC stay below $80k in 2026?", yes_bid=0.55, yes_ask=0.57, event_id="evt-btc-below")
    _add_threshold_market(session, "b90", "Will BTC stay below $90k in 2026?", yes_bid=0.48, yes_ask=0.50, event_id="evt-btc-below")
    session.commit()

    locked = [a for a in scan_logical_arbitrage(session) if a.arb_type == "LOCKED"]
    assert len(locked) == 1
    assert locked[0].strong_market_id == "b80"  # lower threshold is stronger for BELOW
    assert locked[0].weak_market_id == "b90"


def test_monotone_above_ladder_has_no_locked_arb(tmp_path):
    session = _session(tmp_path)
    # Correctly ordered: P($100k) < P($90k). No inversion -> no locked arb.
    _add_threshold_market(session, "m100", "Will BTC reach $100k by 2026?", yes_bid=0.38, yes_ask=0.40)
    _add_threshold_market(session, "m90", "Will BTC reach $90k by 2026?", yes_bid=0.58, yes_ask=0.60)
    session.commit()

    assert [a for a in scan_logical_arbitrage(session) if a.arb_type == "LOCKED"] == []


def test_soft_monotonicity_violation_flagged(tmp_path):
    session = _session(tmp_path)
    # Not lockable (strong_bid 0.55 < weak_ask 0.60 so no risk-free credit),
    # but the mids are clearly out of order: strong mid 0.58 vs weak mid 0.52.
    _add_threshold_market(session, "m100", "Will BTC reach $100k by 2026?", yes_bid=0.55, yes_ask=0.61)
    _add_threshold_market(session, "m90", "Will BTC reach $90k by 2026?", yes_bid=0.49, yes_ask=0.55)
    session.commit()

    arbs = scan_logical_arbitrage(session, monotonicity_tolerance=0.02)
    assert [a for a in arbs if a.arb_type == "LOCKED"] == []
    soft = [a for a in arbs if a.arb_type == "MONOTONICITY"]
    assert len(soft) == 1
    assert soft[0].requires_review is True
    # strong mid 0.58 - weak mid 0.52 = 0.06
    assert abs(soft[0].margin - 0.06) < 1e-9


def test_different_events_not_compared(tmp_path):
    session = _session(tmp_path)
    _add_threshold_market(session, "btc100", "Will BTC reach $100k?", yes_bid=0.60, yes_ask=0.62, event_id="evt-btc")
    _add_threshold_market(session, "eth90", "Will ETH reach $90k?", yes_bid=0.48, yes_ask=0.50, event_id="evt-eth")
    session.commit()
    assert scan_logical_arbitrage(session) == []


def test_different_directions_not_compared(tmp_path):
    session = _session(tmp_path)
    # Same event but one ABOVE and one BELOW -- not a valid ladder pair.
    _add_threshold_market(session, "above100", "Will BTC reach $100k?", yes_bid=0.60, yes_ask=0.62)
    _add_threshold_market(session, "below90", "Will BTC stay below $90k?", yes_bid=0.48, yes_ask=0.50)
    session.commit()
    assert scan_logical_arbitrage(session) == []


def test_different_end_dates_not_compared(tmp_path):
    session = _session(tmp_path)
    _add_threshold_market(session, "m100", "Will BTC reach $100k?", yes_bid=0.60, yes_ask=0.62, end_date=datetime(2026, 6, 30, tzinfo=UTC))
    _add_threshold_market(session, "m90", "Will BTC reach $90k?", yes_bid=0.48, yes_ask=0.50, end_date=datetime(2026, 12, 31, tzinfo=UTC))
    session.commit()
    # Different resolution dates break the subset implication -> no arb.
    assert scan_logical_arbitrage(session) == []


def test_executable_size_limited_by_thinner_leg(tmp_path):
    session = _session(tmp_path)
    _add_threshold_market(session, "m100", "Will BTC reach $100k?", yes_bid=0.60, yes_ask=0.62, depth=30.0)
    _add_threshold_market(session, "m90", "Will BTC reach $90k?", yes_bid=0.48, yes_ask=0.50, depth=120.0)
    session.commit()
    locked = [a for a in scan_logical_arbitrage(session) if a.arb_type == "LOCKED"]
    assert len(locked) == 1
    # Size limited by the thinner (strong bid) leg = 30.
    assert locked[0].executable_size == 30.0
