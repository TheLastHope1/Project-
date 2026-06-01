"""Tests for the book/fee/taxonomy integration into the scanner."""
from datetime import datetime, timedelta, timezone

import pytest

from polymarket_scanner.client import BookLevel, Market, OrderBook
from polymarket_scanner.journal import Journal
from polymarket_scanner.scanner import (
    ScanConfig,
    evaluate_market,
    evaluate_markets,
)


NOW = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)

_FIFTY_FIFTY_RULES = (
    "If this match is incomplete due to forfeiture, disqualification, or "
    "walkover, the market resolves 50/50. Both tokens redeem at $0.50."
)
_ADVANCES_RULES = (
    "If the match is cancelled before play begins, the market resolves 50/50. "
    "Once play has begun, the player who advances through retirement, "
    "default, or disqualification is declared the winner."
)


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
        rules=_FIFTY_FIFTY_RULES,
    )
    defaults.update(over)
    return Market(**defaults)


def _book(asks: list[tuple[float, float]], bids: list[tuple[float, float]] | None = None,
          tick_size=0.01, min_order_size=5, token_id="no") -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[BookLevel(p, s) for p, s in (bids or [])],
        asks=[BookLevel(p, s) for p, s in asks],
        tick_size=tick_size,
        min_order_size=min_order_size,
    )


def test_book_supplies_executable_price_and_depth():
    book = _book(
        asks=[(0.30, 100), (0.32, 200), (0.40, 500)],
        bids=[(0.27, 100), (0.25, 200)],
        token_id="no",
    )
    opp = evaluate_market(_mkt(token_ids=["yes", "no"]), ScanConfig(), now=NOW, book=book)
    assert opp is not None
    assert opp.best_ask == 0.30
    assert opp.best_bid == 0.27
    assert opp.spread == pytest.approx(0.03)
    assert opp.price_source == "clob_book"
    # Depth-weighted VWAP for $100 notional at price 0.30 = ~333 shares.
    # Levels: 100 @ 0.30 + 200 @ 0.32 + 33.3 @ 0.40
    # notional ~= 30 + 64 + 13.33 = 107.33 / 333.3 = ~0.322
    assert opp.target_shares == pytest.approx(100 / 0.30, rel=0.01)
    assert opp.vwap_buy is not None
    assert 0.30 <= opp.vwap_buy <= 0.40


def test_model_ev_uses_taxonomy_probability_fifty():
    # Walkover -> probability_fifty ~0.92. EV should be positive at 0.30 ask.
    book = _book(asks=[(0.30, 1000)], bids=[(0.27, 200)])
    cfg = ScanConfig(paper_target_notional_usd=0)  # disable VWAP so eval price == best_ask
    opp = evaluate_market(_mkt(token_ids=["yes", "no"]), cfg, now=NOW, book=book)
    assert opp is not None
    assert opp.rule_class == "walkover_fifty_fifty"
    assert opp.probability_fifty >= 0.85
    assert opp.model_ev_pct is not None
    assert opp.model_ev_pct > 0.10


def test_advances_rule_class_kills_apparent_edge():
    # Same price, same book, but the rule text says retirement -> advancing
    # player wins. probability_fifty should be much lower and EV should
    # collapse vs the walkover case.
    book = _book(asks=[(0.30, 1000)], bids=[(0.27, 200)])
    cfg = ScanConfig(paper_target_notional_usd=0)
    walkover_opp = evaluate_market(_mkt(token_ids=["yes", "no"], rules=_FIFTY_FIFTY_RULES), cfg, now=NOW, book=book)
    advances_opp = evaluate_market(_mkt(token_ids=["yes", "no"], rules=_ADVANCES_RULES), cfg, now=NOW, book=book)
    assert walkover_opp is not None and advances_opp is not None
    assert walkover_opp.rule_class == "walkover_fifty_fifty"
    assert advances_opp.rule_class == "advances_if_started"
    assert advances_opp.probability_fifty < walkover_opp.probability_fifty
    assert advances_opp.model_ev_pct < walkover_opp.model_ev_pct


def test_strict_mode_drops_never_trade_classes():
    # An explicit "Other" outcome routes resolution to OTHER_OUTCOME, which
    # the binary thesis doesn't apply to. Strict mode should reject it.
    m = _mkt(
        outcomes=["KO", "Decision", "Other"],
        prices=[0.30, 0.40, 0.30],
        rules="If no winner is announced or the fight is cancelled, the market resolves to Other.",
    )
    cfg_loose = ScanConfig(strict_rule_class=False)
    cfg_strict = ScanConfig(strict_rule_class=True)
    # The 3-outcome market won't pass evaluate_market's len()-style screen.
    # Use a binary market with "Other"-routing text instead.
    m = _mkt(
        rules="If the match is cancelled, the market resolves to Other.",
    )
    loose = evaluate_market(m, cfg_loose, now=NOW)
    strict = evaluate_market(m, cfg_strict, now=NOW)
    assert loose is not None
    assert loose.rule_class == "other_outcome"
    assert strict is None


def test_persist_opportunities_writes_to_journal(tmp_path):
    journal = Journal(path=tmp_path / "j.db")

    class FakeClient:
        def iter_active_markets(self):
            return iter([_mkt(token_ids=["yes", "no"])])
        def get_books_batch(self, token_ids):
            return {"no": _book(asks=[(0.30, 100), (0.32, 200)], bids=[(0.27, 100)])}
        def get_best_prices_batch(self, token_ids, side="BUY"):
            return {}

    cfg = ScanConfig(
        persist_opportunities=True,
        journal=journal,
        use_clob_fee_rate=False,
    )
    opps = evaluate_markets([_mkt(token_ids=["yes", "no"])], cfg, now=NOW, client=FakeClient())
    assert len(opps) == 1
    rows = journal.latest_opportunities()
    assert len(rows) == 1
    assert rows[0]["best_ask"] == 0.30
    assert rows[0]["rule_class"] == "walkover_fifty_fifty"
    assert rows[0]["fee_rate"] == 0.03  # sports/CS2 category default
    assert rows[0]["book_snapshot"] is not None


def test_book_fallback_to_price_when_books_missing():
    # Simulate a /books outage by returning empty; /price should fill in.
    from polymarket_scanner.client import TopOfBookQuote

    class FakeClient:
        calls = []

        def get_books_batch(self, token_ids):
            return {}

        def get_best_prices_batch(self, token_ids, side="BUY"):
            self.calls.append((tuple(token_ids), side))
            if side == "SELL":
                return {"no": TopOfBookQuote("no", "SELL", 0.30, "clob_get")}
            return {"no": TopOfBookQuote("no", "BUY", 0.27, "clob_get")}

    client = FakeClient()
    cfg = ScanConfig(use_book=True, use_clob_prices=True)
    opps = evaluate_markets([_mkt(token_ids=["yes", "no"])], cfg, now=NOW, client=client)
    assert len(opps) == 1
    assert opps[0].best_ask == 0.30
    assert opps[0].price_source == "clob_get"


def test_legacy_net_edge_pct_still_present_for_backcompat():
    opp = evaluate_market(_mkt(), ScanConfig(fee_bps=300, slippage_buffer_bps=50), now=NOW)
    # Old field still computed (and not used for ranking).
    assert opp is not None
    assert opp.net_edge_pct is not None
    # Model EV is the new ranking signal.
    assert opp.model_ev_pct is not None


def test_evaluate_markets_does_not_persist_when_flag_off(tmp_path):
    journal = Journal(path=tmp_path / "j.db")

    class FakeClient:
        def get_books_batch(self, token_ids):
            return {}
        def get_best_prices_batch(self, token_ids, side="BUY"):
            return {}

    cfg = ScanConfig(persist_opportunities=False, journal=journal)
    evaluate_markets([_mkt(token_ids=["yes", "no"])], cfg, now=NOW, client=FakeClient())
    assert journal.opportunity_count() == 0
