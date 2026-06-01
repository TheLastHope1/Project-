"""Unit tests for the SQLite paper-trade journal."""
from datetime import datetime, timezone

import pytest

from polymarket_scanner.journal import (
    Journal,
    OpportunitySnapshot,
    rule_hash,
)


NOW = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def journal(tmp_path):
    return Journal(path=tmp_path / "journal.db")


def _snap(**over):
    base = OpportunitySnapshot(
        scan_timestamp=NOW,
        market_id="m1",
        token_id="tokA",
        question="Team A vs Team B",
        category="CS2",
        rule_text="If the match is incomplete by walkover, resolves 50/50.",
        rule_class="walkover_fifty_fifty",
        rule_confidence=0.85,
        probability_fifty=0.92,
        gamma_screen_price=0.20,
        best_bid=0.30,
        best_ask=0.35,
        spread=0.05,
        fee_rate=0.03,
        fee_source="category",
        target_shares=500.0,
        vwap_buy=0.36,
        shares_fillable=500.0,
        model_ev_per_share=0.13,
        model_ev_pct=0.30,
        underdog_outcome="Team B",
        liquidity=10000.0,
        volume24h=5000.0,
        score=72,
        reasons=["category:cs2", "exec_ask"],
        score_reasons=["walkover", "tight-spread"],
        book_snapshot={"asks": [[0.35, 100], [0.36, 400]], "bids": [[0.30, 200]]},
    )
    for k, v in over.items():
        setattr(base, k, v)
    return base


def test_journal_creates_schema_on_first_use(tmp_path):
    db_path = tmp_path / "j.db"
    j = Journal(path=db_path)
    assert db_path.exists()
    assert j.opportunity_count() == 0


def test_record_and_read_back(journal):
    rowid = journal.record_opportunity(_snap())
    assert rowid > 0
    rows = journal.latest_opportunities()
    assert len(rows) == 1
    r = rows[0]
    assert r["market_id"] == "m1"
    assert r["rule_class"] == "walkover_fifty_fifty"
    assert r["best_ask"] == 0.35
    # JSON columns round-trip into lists/dicts.
    assert r["reasons"] == ["category:cs2", "exec_ask"]
    assert r["book_snapshot"]["asks"][0] == [0.35, 100]


def test_multiple_snapshots_per_market_accumulate(journal):
    journal.record_opportunity(_snap())
    journal.record_opportunity(_snap(best_ask=0.34, vwap_buy=0.345))
    journal.record_opportunity(_snap(best_ask=0.33, vwap_buy=0.34))
    history = journal.opportunities_for_market("m1")
    assert len(history) == 3
    # Should be ordered ascending by scan_timestamp (then id).
    assert [h["best_ask"] for h in history] == [0.35, 0.34, 0.33]


def test_record_resolution_idempotent(journal):
    journal.record_resolution(
        "m1",
        resolved_at=NOW,
        winning_outcome="Team B",
        winning_payout=1.0,
    )
    journal.record_resolution(
        "m1",
        resolved_at=NOW,
        winning_outcome="50-50",
        winning_payout=0.5,
        notes="updated after dispute",
    )
    rs = journal.resolutions()
    assert len(rs) == 1
    assert rs[0]["winning_outcome"] == "50-50"
    assert rs[0]["notes"] == "updated after dispute"


def test_realised_pnl_when_underdog_wins(journal):
    # Bought 500 shares at vwap 0.36 with 0.03 fee. Underdog (Team B) wins.
    # cost = 500 * 0.36 + 0.03 * 0.36 * 0.64 * 500 = 180 + 3.456 = 183.456
    # payout = 500 * 1.0 = 500
    # pnl = 500 - 183.456 = 316.544
    journal.record_opportunity(_snap())
    journal.record_resolution(
        "m1",
        resolved_at=NOW,
        winning_outcome="Team B",  # matches underdog_outcome
    )
    summary = journal.realised_pnl_summary()
    assert summary["n_trades"] == 1
    assert summary["total_payout"] == pytest.approx(500.0, abs=0.01)
    assert summary["total_cost"] == pytest.approx(183.456, abs=0.01)
    assert summary["net_pnl"] == pytest.approx(316.544, abs=0.01)
    assert "walkover_fifty_fifty" in summary["per_class"]


def test_realised_pnl_when_resolved_fifty_fifty(journal):
    journal.record_opportunity(_snap())
    journal.record_resolution(
        "m1",
        resolved_at=NOW,
        winning_outcome="50-50",
    )
    summary = journal.realised_pnl_summary()
    # payout = 500 * 0.5 = 250 ; cost ~ 183.456
    assert summary["total_payout"] == pytest.approx(250.0, abs=0.01)
    assert summary["net_pnl"] == pytest.approx(66.544, abs=0.01)


def test_side_semantics_check_persisted(journal):
    journal.record_side_semantics_check(
        checked_at=NOW,
        token_id="tokA",
        ok=False,
        buy_price=0.31,
        sell_price=0.34,
        best_bid=0.30,
        best_ask=0.35,
        notes=["sell_side_disagrees_with_best_ask"],
    )
    with journal._connect() as conn:
        rows = list(conn.execute("SELECT * FROM side_semantics_checks").fetchall())
    assert len(rows) == 1
    assert rows[0]["ok"] == 0
    assert rows[0]["token_id"] == "tokA"


def test_rule_text_corpus_dedups_by_hash(journal):
    snap1 = _snap(rule_text="resolves 50/50 if walkover")
    snap2 = _snap(market_id="m2", rule_text="resolves 50/50 if walkover")
    journal.record_opportunity(snap1)
    journal.record_opportunity(snap2)
    with journal._connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM rule_text_corpus").fetchone()[0]
    assert n == 1  # same rule text -> single corpus entry


def test_export_jsonl(tmp_path, journal):
    journal.record_opportunity(_snap())
    journal.record_opportunity(_snap(market_id="m2", token_id="tokB"))
    out = tmp_path / "out.jsonl"
    with out.open("w") as fp:
        n = journal.export_jsonl(fp)
    assert n == 2
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2


def test_rule_hash_stable():
    h1 = rule_hash("resolves 50/50 on walkover")
    h2 = rule_hash("resolves 50/50 on walkover")
    h3 = rule_hash("resolves 50-50 on walkover")
    assert h1 == h2
    assert h1 != h3
    assert rule_hash("") == ""
    assert rule_hash(None) == ""
