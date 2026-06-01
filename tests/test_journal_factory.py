"""Tests for the journal factory + Postgres backend routing.

The Postgres backend itself is exercised against a mocked ``psycopg``
module so the test suite stays hermetic. Wiring with a real database is
left to the integration test in ``tests/integration/`` (not committed).
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from polymarket_scanner.journal import Journal, make_journal


# ---- factory routing ----------------------------------------------------


def test_make_journal_returns_sqlite_for_file_paths(tmp_path):
    j = make_journal(tmp_path / "j.db")
    assert isinstance(j, Journal)


def test_make_journal_returns_sqlite_for_string_paths(tmp_path):
    j = make_journal(str(tmp_path / "j.db"))
    assert isinstance(j, Journal)


def test_make_journal_routes_postgres_urls_to_pg_backend(monkeypatch, tmp_path):
    # Install a stub `psycopg` module so PostgresJournal imports cleanly
    # and the connect() / schema-creation path is testable without a real DB.
    fake_psycopg = types.ModuleType("psycopg")
    conn = MagicMock(name="connection")
    cur = MagicMock(name="cursor")
    conn.cursor.return_value.__enter__.return_value = cur
    fake_psycopg.connect = MagicMock(return_value=conn)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    j = make_journal("postgres://user:pass@host:5432/db")
    from polymarket_scanner.journal_postgres import PostgresJournal
    assert isinstance(j, PostgresJournal)
    # The schema bootstrap should have run on init.
    fake_psycopg.connect.assert_called()
    cur.execute.assert_called()


def test_make_journal_accepts_postgresql_scheme(monkeypatch):
    fake_psycopg = types.ModuleType("psycopg")
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = MagicMock()
    fake_psycopg.connect = MagicMock(return_value=conn)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    j = make_journal("postgresql://u:p@h/db")
    from polymarket_scanner.journal_postgres import PostgresJournal
    assert isinstance(j, PostgresJournal)


def test_make_journal_env_var_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("POLY_JOURNAL_URL", "")
    monkeypatch.setenv("POLY_JOURNAL_PATH", str(tmp_path / "from_env.db"))
    j = make_journal()
    assert isinstance(j, Journal)


# ---- PostgresJournal write paths ----------------------------------------


@pytest.fixture
def pg_journal(monkeypatch):
    """A PostgresJournal whose underlying psycopg is mocked.

    The mocked cursor records every executed SQL string so tests can
    assert which queries fired without needing a real database.
    """
    fake_psycopg = types.ModuleType("psycopg")
    conn = MagicMock(name="conn")
    cur = MagicMock(name="cur")
    cur.fetchone.return_value = (42,)  # default return for RETURNING id
    cur.fetchall.return_value = []
    cur.description = []
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    fake_psycopg.connect = MagicMock(return_value=conn)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    from polymarket_scanner.journal_postgres import PostgresJournal
    pg = PostgresJournal("postgres://u:p@h/db")
    return pg, fake_psycopg, conn, cur


def test_postgres_record_opportunity_inserts_with_returning(pg_journal):
    pg, _fake, _conn, cur = pg_journal
    from datetime import datetime, timezone
    from polymarket_scanner.journal import OpportunitySnapshot

    snap = OpportunitySnapshot(
        scan_timestamp=datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        market_id="m1",
        token_id="tokA",
        question="A vs B",
        rule_text="resolves 50/50 on walkover",
        rule_class="walkover_fifty_fifty",
        rule_confidence=0.85,
        probability_fifty=0.92,
        best_bid=0.30,
        best_ask=0.35,
        fee_rate=0.03,
        target_shares=500.0,
        vwap_buy=0.36,
        underdog_outcome="B",
        reasons=["category:cs2"],
        score_reasons=["walkover"],
        book_snapshot={"asks": [[0.35, 100]]},
    )
    rowid = pg.record_opportunity(snap)
    assert rowid == 42
    # The first SQL fired should be the corpus upsert; the second the
    # opportunity insert. We don't strictly assert ordering -- just that
    # both ran.
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "rule_text_corpus" in executed
    assert "INSERT INTO opportunities" in executed
    assert "RETURNING id" in executed


def test_postgres_record_resolution_uses_on_conflict_upsert(pg_journal):
    pg, _fake, _conn, cur = pg_journal
    from datetime import datetime, timezone

    pg.record_resolution(
        "m1",
        resolved_at=datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        winning_outcome="50-50",
        winning_payout=0.5,
    )
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    # Schema creation runs first; the resolution insert comes later.
    assert "INSERT INTO resolutions" in executed
    assert "ON CONFLICT (market_id) DO UPDATE" in executed


def test_postgres_side_semantics_persisted(pg_journal):
    pg, _fake, _conn, cur = pg_journal
    from datetime import datetime, timezone

    pg.record_side_semantics_check(
        checked_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        token_id="tokA",
        ok=False,
        buy_price=0.31,
        sell_price=0.34,
        best_bid=0.30,
        best_ask=0.35,
        notes=["sell_side_disagrees_with_best_ask"],
    )
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "INSERT INTO side_semantics_checks" in executed


def test_postgres_realised_pnl_summary_uses_join(pg_journal):
    pg, _fake, _conn, cur = pg_journal
    # No matching rows -> empty summary.
    cur.description = [("market_id",)]
    cur.fetchall.return_value = []
    summary = pg.realised_pnl_summary()
    assert summary["n_trades"] == 0
    assert summary["total_cost"] == 0
    executed = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
    assert "JOIN resolutions" in executed


def test_postgres_url_classifier():
    from polymarket_scanner.journal_postgres import is_postgres_url
    assert is_postgres_url("postgres://u:p@h:5432/d")
    assert is_postgres_url("postgresql://u:p@h/d")
    assert is_postgres_url("POSTGRES://U:P@H/D")
    assert not is_postgres_url("journal.db")
    assert not is_postgres_url("/tmp/journal.db")
    assert not is_postgres_url("")
    assert not is_postgres_url(None)
