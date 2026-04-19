"""Unit tests for evaluate_market - no network required."""
from datetime import datetime, timedelta, timezone

from polymarket_scanner.client import Market
from polymarket_scanner.scanner import ScanConfig, evaluate_market


NOW = datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc)


def _mkt(**over):
    defaults = dict(
        id="m1",
        question="FaZe vs eyeballers - winner?",
        slug="faze-eyeballers",
        end_date=NOW + timedelta(hours=1),
        active=True,
        closed=False,
        accepting_orders=True,
        outcomes=["FaZe", "eyeballers"],
        prices=[0.80, 0.20],
        volume=5000.0,
        liquidity=10000.0,
        category="CS2",
        event_title="IEM Katowice",
    )
    defaults.update(over)
    return Market(**defaults)


def test_flags_imminent_esports_underdog():
    opp = evaluate_market(_mkt(), ScanConfig(), now=NOW)
    assert opp is not None
    assert opp.underdog_outcome == "eyeballers"
    assert opp.underdog_price == 0.20
    assert opp.edge_pct > 1.4  # 0.50/0.20 - 1 = 1.5


def test_flags_past_end_still_open():
    # Event was 30 min ago but market still accepting orders - strongest signal.
    m = _mkt(end_date=NOW - timedelta(minutes=30))
    opp = evaluate_market(m, ScanConfig(), now=NOW)
    assert opp is not None
    assert any("past_end" in r for r in opp.reasons)


def test_rejects_when_underdog_too_expensive():
    # Coin flip market: no edge even if forfeit.
    m = _mkt(prices=[0.55, 0.45])
    assert evaluate_market(m, ScanConfig(max_underdog_price=0.40), now=NOW) is None


def test_rejects_low_liquidity():
    m = _mkt(liquidity=50.0)
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_rejects_unrelated_category_without_watchlist():
    m = _mkt(category="Politics", event_title="US Election", question="Will X win?")
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_watchlist_matches():
    m = _mkt(category="Politics", event_title="", question="Will FaZe clan show up?")
    cfg = ScanConfig(team_watchlist=("FaZe",))
    opp = evaluate_market(m, cfg, now=NOW)
    assert opp is not None
    assert any(r.startswith("watchlist:") for r in opp.reasons)


def test_rejects_closed_market():
    assert evaluate_market(_mkt(closed=True), ScanConfig(), now=NOW) is None
    assert evaluate_market(_mkt(accepting_orders=False), ScanConfig(), now=NOW) is None
