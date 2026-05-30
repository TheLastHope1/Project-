"""SQLite paper-trade journal.

Edge claims are only meaningful if they can be measured. This module
persists every opportunity snapshot the scanner produces -- including the
order-book context (best bid/ask, depth, tick, fee rate) and the model EV
that justified the alert -- so that later, when the underlying market
resolves, realised PnL can be computed and compared against the model.

It also records side-semantics validation results (``/price`` vs ``/book``
contract checks) so a quiet API drift can't silently invalidate edge claims.

Storage is a single SQLite file. Default path: ``./journal.db``. Override
with ``$POLY_JOURNAL_PATH`` for tests or alternate deployments. SQLite is
chosen deliberately: zero ops, single-file, easy to ``sqlite3`` from the
terminal, and ``WAL`` mode lets the scanner thread and the dashboard read
concurrently.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


DEFAULT_JOURNAL_PATH = Path(os.environ.get("POLY_JOURNAL_PATH", "journal.db"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_timestamp TEXT NOT NULL,
    event_id TEXT,
    market_id TEXT NOT NULL,
    slug TEXT,
    token_id TEXT,
    question TEXT,
    category TEXT,
    event_title TEXT,
    game_start_time TEXT,
    rule_hash TEXT,
    rule_class TEXT,
    rule_confidence REAL,
    probability_fifty REAL,
    gamma_screen_price REAL,
    best_bid REAL,
    best_ask REAL,
    spread REAL,
    tick_size REAL,
    min_order_size REAL,
    ask_depth_usd REAL,
    target_shares REAL,
    vwap_buy REAL,
    shares_fillable REAL,
    fee_rate REAL,
    fee_source TEXT,
    model_ev_per_share REAL,
    model_ev_pct REAL,
    underdog_outcome TEXT,
    liquidity REAL,
    volume24h REAL,
    score INTEGER,
    reasons TEXT,
    score_reasons TEXT,
    book_snapshot TEXT
);
CREATE INDEX IF NOT EXISTS idx_opp_market ON opportunities(market_id, scan_timestamp);
CREATE INDEX IF NOT EXISTS idx_opp_class ON opportunities(rule_class, scan_timestamp);

CREATE TABLE IF NOT EXISTS resolutions (
    market_id TEXT PRIMARY KEY,
    resolved_at TEXT NOT NULL,
    winning_outcome TEXT,
    winning_payout REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS side_semantics_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    token_id TEXT NOT NULL,
    ok INTEGER NOT NULL,
    buy_price REAL,
    sell_price REAL,
    best_bid REAL,
    best_ask REAL,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_semantics_token ON side_semantics_checks(token_id, checked_at);

CREATE TABLE IF NOT EXISTS rule_text_corpus (
    rule_hash TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    rule_text TEXT NOT NULL
);
"""


@dataclass
class OpportunitySnapshot:
    """All the fields needed to journal an opportunity at scan time.

    Constructed from a scanner ``Opportunity`` plus the order-book context
    that justified its ranking. See ``Journal.record_opportunity``.
    """

    scan_timestamp: datetime
    market_id: str
    event_id: str | None = None
    slug: str | None = None
    token_id: str | None = None
    question: str | None = None
    category: str | None = None
    event_title: str | None = None
    game_start_time: datetime | None = None
    rule_text: str | None = None
    rule_class: str | None = None
    rule_confidence: float | None = None
    probability_fifty: float | None = None
    gamma_screen_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    tick_size: float | None = None
    min_order_size: float | None = None
    ask_depth_usd: float | None = None
    target_shares: float | None = None
    vwap_buy: float | None = None
    shares_fillable: float | None = None
    fee_rate: float | None = None
    fee_source: str | None = None
    model_ev_per_share: float | None = None
    model_ev_pct: float | None = None
    underdog_outcome: str | None = None
    liquidity: float | None = None
    volume24h: float | None = None
    score: int | None = None
    reasons: list[str] = field(default_factory=list)
    score_reasons: list[str] = field(default_factory=list)
    book_snapshot: dict[str, Any] | None = None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def rule_hash(rule_text: str | None) -> str:
    """Stable hash of the rule text so duplicate wordings don't multiply
    corpus entries. Returns empty string for empty inputs."""
    if not rule_text:
        return ""
    return hashlib.sha1(rule_text.encode("utf-8")).hexdigest()


class Journal:
    """Thread-safe wrapper over a single SQLite file.

    All write methods take the lock. Reads use short-lived connections.
    """

    def __init__(self, path: Path | str = DEFAULT_JOURNAL_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _writer(self):
        with self._lock:
            conn = self._connect()
            try:
                yield conn
            finally:
                conn.close()

    # ---- writes ----------------------------------------------------------

    def record_opportunity(self, snap: OpportunitySnapshot) -> int:
        """Persist one opportunity snapshot. Returns the inserted row id.

        Append-only by design. Multiple snapshots for the same market are
        expected -- they form the per-market price history that lets us
        spot late-breaking information vs. early signals.
        """
        rh = rule_hash(snap.rule_text)
        with self._writer() as conn:
            if rh and snap.rule_text:
                conn.execute(
                    "INSERT OR IGNORE INTO rule_text_corpus(rule_hash, first_seen_at, rule_text) VALUES (?, ?, ?)",
                    (rh, _iso(snap.scan_timestamp), snap.rule_text),
                )
            cur = conn.execute(
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
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    _iso(snap.scan_timestamp), snap.event_id, snap.market_id, snap.slug,
                    snap.token_id, snap.question,
                    snap.category, snap.event_title, _iso(snap.game_start_time),
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
            return int(cur.lastrowid or 0)

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
            conn.execute(
                """
                INSERT INTO resolutions(market_id, resolved_at, winning_outcome, winning_payout, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(market_id) DO UPDATE SET
                    resolved_at=excluded.resolved_at,
                    winning_outcome=excluded.winning_outcome,
                    winning_payout=excluded.winning_payout,
                    notes=excluded.notes
                """,
                (market_id, _iso(resolved_at), winning_outcome, winning_payout, notes),
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
            conn.execute(
                """
                INSERT INTO side_semantics_checks(
                    checked_at, token_id, ok, buy_price, sell_price, best_bid, best_ask, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _iso(checked_at), token_id, 1 if ok else 0,
                    buy_price, sell_price, best_bid, best_ask,
                    json.dumps(notes or []),
                ),
            )

    # ---- reads -----------------------------------------------------------

    def opportunity_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0])

    def latest_opportunities(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM opportunities ORDER BY scan_timestamp DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def opportunities_for_market(self, market_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM opportunities WHERE market_id=? ORDER BY scan_timestamp ASC",
                (market_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def resolutions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM resolutions").fetchall()
        return [dict(r) for r in rows]

    def realised_pnl_summary(self) -> dict[str, Any]:
        """Join opportunities to resolutions and compute the buy-and-hold PnL.

        For each (market_id, token_id, scan_timestamp) opportunity, simulate
        buying ``target_shares`` at ``vwap_buy`` (or ``best_ask`` if vwap is
        null), paying the recorded fee rate, and redeeming at the resolved
        payout. Aggregates across all resolved markets in the journal.
        """
        with self._connect() as conn:
            rows = conn.execute(
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
            ).fetchall()

        total_cost = 0.0
        total_payout = 0.0
        total_fee = 0.0
        n_trades = 0
        per_class: dict[str, dict[str, float]] = {}
        for r in rows:
            shares = float(r["target_shares"] or 0)
            if shares <= 0:
                continue
            ask = float(r["vwap_buy"] or r["best_ask"] or 0)
            if ask <= 0:
                continue
            rate = float(r["fee_rate"] or 0)
            fee = rate * ask * (1.0 - ask) * shares
            cost = ask * shares + fee
            payout = 0.0
            # Decide payout: if recorded winning_payout fits the underdog token,
            # use it; otherwise assume 1.0 if the underdog won, 0.5 if the
            # market notes mention a 50/50 resolution, else 0.
            wp = r["winning_payout"]
            wo = (r["winning_outcome"] or "").strip().lower()
            udo = (r["underdog_outcome"] or "").strip().lower()
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

            key = r["rule_class"] or "unknown"
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
        """Stream the chosen table as JSONL to a writable file-like ``fp``.
        Returns the number of rows written.
        """
        if table not in {"opportunities", "resolutions", "side_semantics_checks", "rule_text_corpus"}:
            raise ValueError(f"unknown table: {table}")
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        n = 0
        for row in rows:
            fp.write(json.dumps(_row_to_dict(row)) + "\n")
            n += 1
        return n


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("reasons", "score_reasons", "book_snapshot", "notes"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, json.JSONDecodeError):
                pass
    return d


# A module-level singleton is convenient for the scanner+web layer to share
# without threading a Journal instance through every call site. Tests should
# instantiate ``Journal(path=...)`` directly and never touch this global.
_default_journal: Journal | None = None
_default_lock = threading.Lock()


def get_default_journal() -> Journal:
    """Return (and lazily create) the process-wide default Journal."""
    global _default_journal
    with _default_lock:
        if _default_journal is None:
            _default_journal = Journal(DEFAULT_JOURNAL_PATH)
        return _default_journal


def reset_default_journal_for_tests(journal: Journal | None) -> None:
    """Override the module-level singleton. Tests only."""
    global _default_journal
    with _default_lock:
        _default_journal = journal


def make_journal(url_or_path: str | Path | None = None):
    """Factory returning the right Journal backend for the given target.

    - ``postgres://`` / ``postgresql://`` → ``PostgresJournal`` (Supabase,
      Vercel Postgres, Neon, self-hosted). Required for serverless deploys
      where local SQLite is per-instance ephemeral.
    - Anything else (or ``None``) → SQLite ``Journal`` at that path, or
      ``$POLY_JOURNAL_URL`` env var, or ``$POLY_JOURNAL_PATH``, or
      ``journal.db``.

    Lazy-imports ``PostgresJournal`` so SQLite-only users don't pay the
    psycopg cold-start cost.
    """
    if url_or_path is None:
        url_or_path = os.environ.get("POLY_JOURNAL_URL") or os.environ.get("POLY_JOURNAL_PATH") or "journal.db"
    if isinstance(url_or_path, Path):
        return Journal(path=url_or_path)
    val = str(url_or_path).strip()
    if val.startswith(("postgres://", "postgresql://")):
        from .journal_postgres import PostgresJournal
        return PostgresJournal(val)
    return Journal(path=val)
