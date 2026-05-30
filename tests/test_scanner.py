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


def test_hard_profitability_floor_rejects_price_above_50c():
    # A generous --max-price > 0.5 must NOT unlock break-even alerts. The
    # 50/50 payout is $0.50/share, so anything >= $0.50 is at best zero
    # gross edge (negative after fees). Codex review caught this on PR #4.
    #
    # Realistic scenario: the Gamma midpoint shows the underdog at 0.20 (so
    # the screen filter waves it through), but the executable best ask on
    # /book is 0.51 because the book moved while the midpoint hadn't ticked.
    # Without the hard floor, --max-price=0.60 would still produce an alert
    # at 0.51 with negative gross edge.
    from polymarket_scanner.client import TopOfBookQuote
    m = _mkt(token_ids=["yes", "no"])
    cfg = ScanConfig(max_underdog_price=0.60, max_screen_price=0.60)
    opp = evaluate_market(
        m, cfg, now=NOW,
        execution_quote=TopOfBookQuote("no", "SELL", 0.51, "clob_test"),
    )
    assert opp is None


def test_rejects_low_liquidity():
    m = _mkt(liquidity=50.0)
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_rejects_unrelated_category_without_watchlist():
    m = _mkt(category="Politics", event_title="US Election", question="Will X win?")
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_watchlist_matches():
    m = _mkt(
        category="CS2",
        event_title="",
        question="Will FaZe show up tonight?",
        end_date=NOW + timedelta(hours=2),
    )
    cfg = ScanConfig(team_watchlist=("FaZe",))
    opp = evaluate_market(m, cfg, now=NOW)
    assert opp is not None
    assert any(r.startswith("watchlist:") for r in opp.reasons)


def test_rejects_closed_market():
    assert evaluate_market(_mkt(closed=True), ScanConfig(), now=NOW) is None
    assert evaluate_market(_mkt(accepting_orders=False), ScanConfig(), now=NOW) is None


def test_rejects_outright_season_winner_without_h2h():
    # "Will X win the 2026 season" - not head-to-head, no forfeit risk.
    m = _mkt(
        question="Will LNG Esports win the LPL 2026 season?",
        category="esports",
        end_date=NOW + timedelta(days=120),
        prices=[0.993, 0.007],
    )
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_mma_does_not_match_emma():
    # Word-boundary check: "mma" in "Emma" must not trigger a category hit.
    m = _mkt(
        question="Will Emma Raducanu beat Iga Swiatek?",
        category="Tennis",  # legit match via "tennis" keyword, not "mma"
        event_title="Wimbledon",
        end_date=NOW + timedelta(hours=3),
    )
    opp = evaluate_market(m, ScanConfig(), now=NOW)
    assert opp is not None
    assert any(r == "category:tennis" for r in opp.reasons)
    assert not any("mma" in r for r in opp.reasons)


def test_mma_does_not_match_commanders():
    # "Commanders agree to name stadium after Trump" - not a match, not sports forfeit.
    m = _mkt(
        question="Washington Commanders agree to name stadium after Trump?",
        category="Politics",
        event_title="",
        end_date=NOW + timedelta(days=60),
        prices=[0.95, 0.05],
    )
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_requires_imminent_timing():
    # H2H + esports category but event is 6 months away - skip.
    m = _mkt(end_date=NOW + timedelta(days=180))
    assert evaluate_market(m, ScanConfig(), now=NOW) is None


def test_preserves_outcome_price_mapping_with_blank_gamma_price():
    from polymarket_scanner.client import _parse_market

    row = {
        "id": "m2",
        "question": "Team A vs Team B",
        "slug": "a-b",
        "endDate": "2026-04-19T13:00:00Z",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "outcomes": '["Team A", "Team B"]',
        "outcomePrices": '["", "0.24"]',
        "clobTokenIds": '["tokA", "tokB"]',
        "volume": 1000,
        "liquidity": 1000,
        "category": "CS2",
    }
    market = _parse_market(row)
    assert market is not None
    assert market.prices == [None, 0.24]
    assert market.underdog_outcome == "Team B"
    assert market.underdog_token_id == "tokB"


def test_uses_clob_ask_for_edge_when_available():
    from polymarket_scanner.client import TopOfBookQuote

    m = _mkt(token_ids=["yes", "no"])
    opp = evaluate_market(
        m,
        ScanConfig(),
        now=NOW,
        execution_quote=TopOfBookQuote("no", "SELL", 0.30, "clob_test"),
        bid_quote=TopOfBookQuote("no", "BUY", 0.27, "clob_test"),
    )
    assert opp is not None
    assert opp.underdog_price == 0.30
    assert opp.screen_price == 0.20
    assert opp.price_source == "clob_test"
    assert opp.spread == 0.03
    assert "exec_ask" in opp.reasons


def test_require_clob_price_drops_gamma_only_candidate():
    cfg = ScanConfig(require_clob_price=True)
    assert evaluate_market(_mkt(), cfg, now=NOW) is None


def test_evaluate_markets_uses_sell_side_as_executable_ask():
    from polymarket_scanner.client import TopOfBookQuote
    from polymarket_scanner.scanner import evaluate_markets

    class FakeClient:
        def __init__(self):
            self.calls = []
        def get_best_prices_batch(self, token_ids, side="BUY"):
            self.calls.append((tuple(token_ids), side))
            if side == "SELL":
                return {"no": TopOfBookQuote("no", "SELL", 0.30, "clob_ask")}
            return {"no": TopOfBookQuote("no", "BUY", 0.27, "clob_bid")}

    client = FakeClient()
    opps = evaluate_markets([_mkt(token_ids=["yes", "no"])], ScanConfig(), now=NOW, client=client)

    assert client.calls == [(("no",), "SELL"), (("no",), "BUY")]
    assert len(opps) == 1
    assert opps[0].underdog_price == 0.30
    assert opps[0].best_ask == 0.30
    assert opps[0].best_bid == 0.27


def test_run_forever_reuses_single_market_snapshot_for_signals():
    from polymarket_scanner.scanner import run_forever

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def iter_active_markets(self):
            self.calls += 1
            return iter([_mkt()])
        def get_best_prices_batch(self, token_ids, side="BUY"):
            return {}

    client = FakeClient()
    snapshots = []
    run_forever(
        client,
        ScanConfig(use_clob_prices=False),
        on_opportunity=lambda opp: None,
        max_iterations=1,
        on_markets_scanned=lambda markets: snapshots.append(list(markets)),
    )
    assert client.calls == 1
    assert len(snapshots) == 1
    assert len(snapshots[0]) == 1
