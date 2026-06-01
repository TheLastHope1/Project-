"""Postgres-backed journal for serverless and shared deployments.

Vercel serverless functions get a read-only filesystem (only ``/tmp`` is
writable, and even ``/tmp`` is per-instance and ephemeral). SQLite stops
being useful as soon as the same data needs to outlive a single warm
container. This module provides a drop-in ``PostgresJournal`` with the same
public API as ``journal.Journal`` so callers don't care which backend is
live.

Designed to work against any Postgres -- Supabase, Vercel Postgres, Neon,
self-hosted -- as long as ``POLY_JOURNAL_URL`` is a ``postgres://`` /
``postgresql://`` connection string. Supabase users should use the *session
pooler* connection string (port 5432, ``pgbouncer=true`` flag in the URL)
because serverless functions reconnect on every cold start.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from .journal import OpportunitySnapshot, rule_hash

log = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id BIGSERIAL PRIMARY KEY,
    scan_timestamp TIMESTAMPTZ NOT NULL,
    event_id TEXT,
    market_id TEXT NOT NULL,
    slug TEXT,
    token_id TEXT,
    question TEXT,
    category TEXT,
    event_title TEXT,
    game_start_time TIMESTAMPTZ,
    rule_hash TEXT,
    rule_class TEXT,
    rule_confidence DOUBLE PRECISION,
    probability_fifty DOUBLE PRECISION,
    gamma_screen_price DOUBLE PRECISION,
    best_bid DOUBLE PRECISION,
    best_ask DOUBLE PRECISION,
    spread DOUBLE PRECISION,
    tick_size DOUBLE PRECISION,
    min_order_size DOUBLE PRECISION,
    ask_depth_usd DOUBLE PRECISION,
    target_shares DOUBLE PRECISION,
    vwap_buy DOUBLE PRECISION,
    shares_fillable DOUBLE PRECISION,
    fee_rate DOUBLE PRECISION,
    fee_source TEXT,
    model_ev_per_share DOUBLE PRECISION,
    model_ev_pct DOUBLE PRECISION,
    underdog_outcome TEXT,
    liquidity DOUBLE PRECISION,
    volume24h DOUBLE PRECISION,
    score INTEGER,
    reasons JSONB,
    score_reasons JSONB,
    book_snapshot JSONB
);
CREATE INDEX IF NOT EXISTS idx_opp_market ON opportunities(market_id, scan_timestamp);
CREATE INDEX IF NOT EXISTS idx_opp_class ON opportunities(rule_class, scan_timestamp);

CREATE TABLE IF NOT EXISTS resolutions (
    market_id TEXT PRIMARY KEY,
    resolved_at TIMESTAMPTZ NOT NULL,
    winning_outcome TEXT,
    winning_payout DOUBLE PRECISION,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS side_semantics_checks (
    id BIGSERIAL PRIMARY KEY,
    checked_at TIMESTAMPTZ NOT NULL,
    token_id TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    buy_price DOUBLE PRECISION,
    sell_price DOUBLE PRECISION,
    best_bid DOUBLE PRECISION,
    best_ask DOUBLE PRECISION,
    notes JSONB
);
CREATE INDEX IF NOT EXISTS idx_semantics_token ON side_semantics_checks(token_id, checked_at);

CREATE TABLE IF NOT EXISTS rule_text_corpus (
    rule_hash TEXT PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL,
    rule_text TEXT NOT NULL
);
"""


def _ensure_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class PostgresJournal:
    """Drop-in Postgres replacement for ``journal.Journal``.

    Uses ``psycopg`` (v3). Connections are short-lived to keep serverless
    cold-start memory small and to play nicely with PgBouncer / Supabase
    session pooler in front of the database.
    """

    def __init__(self, url: str):
        # Lazy import so SQLite-only users don't pay the binary-wheel cost.
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:  # pragma: no cover - guard for misconfig
            raise RuntimeError(
                "psycopg is required for the Postgres journal backend. "
                "Add `psycopg[binary]>=3.1.18` to requirements.txt."
            ) from exc

        self.url = url
        self._lock = threading.Lock()
        self._ensure_schema()

    # ---- connection helpers ---------------------------------------------

    def _connect(self):
        import psycopg
        # autocommit=False -> we explicitly commit at the end of each writer
        # block. Read methods use a fresh connection and don't write.
        return psycopg.connect(self.url, autocommit=False, connect_timeout=10)

    @contextmanager
    def _writer(self):
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    @contextmanager
    def _reader(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._writer() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)

    # ---- writes ----------------------------------------------------------

    def record_opportunity(self, snap: OpportunitySnapshot) -> int:
        rh = rule_hash(snap.rule_text)
        with self._writer() as conn:
            with conn.cursor() as cur:
                if rh and snap.rule_text:
                    cur.execute(
                        "INSERT INTO rule_text_corpus(rule_hash, first_seen_at, rule_text) "
                        "VALUES (%s, %s, %s) ON CONFLICT (rule_hash) DO NOTHING",
                        (rh, _ensure_dt(snap.scan_timestamp), snap.rule_text),
                    )
                cur.execute(
                    """
                    INSERT INTO opportunities(
                        scan_timestamp, event_id, market_id, slug, token_id, question,
                        category, event_title, game_start_time, rule_hash, rule_class,
                        rule_confidence, probability_fifty,
                        gamma_screen_price, best_bid, best_ask, spread,
                        tick_size, min_order_size, ask_depth_usd, target_shares,
                        vwap_buy, shares_fillable,
                        fee_rate, fee_source,
                        model_ev_per_share, model_ev_pct,
                        underdog_outcome, liquidity, volume24h,
                        score, reasons, score_reasons, book_snapshot
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s::jsonb, %s::jsonb, %s::jsonb
                    )
                    RETURNING id
                    """,
                    (
                        _ensure_dt(snap.scan_timestamp), snap.event_id, snap.market_id, snap.slug,
                        snap.token_id, snap.question,
                        snap.category, snap.event_title, _ensure_dt(snap.game_start_time),
                        rh or None, snap.rule_class,
                        snap.rule_confidence, snap.probability_fifty,
                        snap.gamma_screen_price, snap.best_bid, snap.best_ask, snap.spread,
                        snap.tick_size, snap.min_order_size, snap.ask_depth_usd, snap.target_shares,
                        snap.vwap_buy, snap.shares_fillable,
                        snap.fee_rate, snap.fee_source,
                        snap.model_ev_per_share, snap.model_ev_pct,
                        snap.underdog_outcome, snap.liquidity, snap.volume24h,
                        snap.score,
                        json.dumps(snap.reasons),
                        json.dumps(snap.score_reasons),
                        json.dumps(snap.book_snapshot) if snap.book_snapshot else None,
                    ),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def record_resolution(
        self,
        market_id: str,
        *,
        resolved_at: datetime,
        winning_outcome: str | None,
        winning_payout: float | None = None,
        notes: str | None = None,
    ) -> None:
        with self._writer() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resolutions(market_id, resolved_at, winning_outcome, winning_payout, notes)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (market_id) DO UPDATE SET
                        resolved_at=excluded.resolved_at,
                        winning_outcome=excluded.winning_outcome,
                        winning_payout=excluded.winning_payout,
                        notes=excluded.notes
                    """,
                    (market_id, _ensure_dt(resolved_at), winning_outcome, winning_payout, notes),
                )

    def record_side_semantics_check(
        self,
        *,
        checked_at: datetime,
        token_id: str,
        ok: bool,
        buy_price: float | None,
        sell_price: float | None,
        best_bid: float | None,
        best_ask: float | None,
        notes: list[str] | None = None,
    ) -> None:
        with self._writer() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO side_semantics_checks(
                        checked_at, token_id, ok, buy_price, sell_price, best_bid, best_ask, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        _ensure_dt(checked_at), token_id, bool(ok),
                        buy_price, sell_price, best_bid, best_ask,
                        json.dumps(notes or []),
                    ),
                )

    # ---- reads -----------------------------------------------------------

    def opportunity_count(self) -> int:
        with self._reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM opportunities")
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def _rows_as_dicts(self, cur) -> list[dict[str, Any]]:
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k, v in list(d.items()):
                if isinstance(v, datetime):
                    d[k] = v.astimezone(timezone.utc).isoformat()
            out.append(d)
        return out

    def latest_opportunities(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._reader() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM opportunities ORDER BY scan_timestamp DESC, id DESC LIMIT %s",
                    (int(limit),),
                )
                return self._rows_as_dicts(cur)

    def opportunities_for_market(self, market_id: str) -> list[dict[str, Any]]:
        with self._reader() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM opportunities WHERE market_id=%s ORDER BY scan_timestamp ASC",
                    (market_id,),
                )
                return self._rows_as_dicts(cur)

    def resolutions(self) -> list[dict[str, Any]]:
        with self._reader() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM resolutions")
                return self._rows_as_dicts(cur)

    def realised_pnl_summary(self) -> dict[str, Any]:
        """Same shape as ``Journal.realised_pnl_summary``. The Postgres
        implementation does the join in SQL but the per-trade PnL maths
        runs in Python so the two backends produce identical numbers.
        """
        with self._reader() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        o.market_id, o.token_id, o.scan_timestamp, o.target_shares,
                        o.vwap_buy, o.best_ask, o.fee_rate, o.rule_class, o.score,
                        o.underdog_outcome,
                        r.winning_outcome, r.winning_payout, r.resolved_at
                    FROM opportunities o
                    JOIN resolutions r ON r.market_id = o.market_id
                    WHERE o.target_shares > 0
                    """
                )
                rows = self._rows_as_dicts(cur)

        total_cost = 0.0
        total_payout = 0.0
        total_fee = 0.0
        n_trades = 0
        per_class: dict[str, dict[str, float]] = {}
        for r in rows:
            shares = float(r.get("target_shares") or 0)
            if shares <= 0:
                continue
            ask = float(r.get("vwap_buy") or r.get("best_ask") or 0)
            if ask <= 0:
                continue
            rate = float(r.get("fee_rate") or 0)
            fee = rate * ask * (1.0 - ask) * shares
            cost = ask * shares + fee
            wp = r.get("winning_payout")
            wo = (r.get("winning_outcome") or "").strip().lower()
            udo = (r.get("underdog_outcome") or "").strip().lower()
            if wp is not None:
                payout = float(wp) * shares
            elif wo == udo and udo:
                payout = 1.0 * shares
            elif wo in {"50-50", "50/50", "fifty-fifty", "split"}:
                payout = 0.5 * shares
            else:
                payout = 0.0
            total_cost += cost
            total_payout += payout
            total_fee += fee
            n_trades += 1
            key = r.get("rule_class") or "unknown"
            bucket = per_class.setdefault(key, {"cost": 0.0, "payout": 0.0, "fee": 0.0, "n": 0.0})
            bucket["cost"] += cost
            bucket["payout"] += payout
            bucket["fee"] += fee
            bucket["n"] += 1

        return {
            "n_trades": n_trades,
            "total_cost": round(total_cost, 4),
            "total_payout": round(total_payout, 4),
            "total_fee": round(total_fee, 4),
            "net_pnl": round(total_payout - total_cost, 4),
            "roi": round((total_payout - total_cost) / total_cost, 4) if total_cost > 0 else 0.0,
            "per_class": {
                k: {
                    "n": int(v["n"]),
                    "cost": round(v["cost"], 4),
                    "payout": round(v["payout"], 4),
                    "fee": round(v["fee"], 4),
                    "net_pnl": round(v["payout"] - v["cost"], 4),
                    "roi": round((v["payout"] - v["cost"]) / v["cost"], 4) if v["cost"] > 0 else 0.0,
                }
                for k, v in per_class.items()
            },
        }

    def export_jsonl(self, fp, *, table: str = "opportunities") -> int:
        allowed = {"opportunities", "resolutions", "side_semantics_checks", "rule_text_corpus"}
        if table not in allowed:
            raise ValueError(f"unknown table: {table}")
        with self._reader() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {table}")
                rows = self._rows_as_dicts(cur)
        for row in rows:
            fp.write(json.dumps(row, default=str) + "\n")
        return len(rows)


def is_postgres_url(value: str) -> bool:
    """Cheap classifier: does this look like a Postgres connection string?"""
    if not value:
        return False
    v = value.strip().lower()
    return v.startswith("postgres://") or v.startswith("postgresql://")
