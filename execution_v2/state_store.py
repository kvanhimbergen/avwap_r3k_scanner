"""
Execution V2 – SQLite State Store

Goals:
- Single-writer, restart-safe persistence for execution state.
- Idempotency keys to prevent duplicate orders on restarts.
- Minimal schema aligned to Execution V2 contracts.

This module must remain strategy-agnostic.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import asdict
from typing import Optional, Iterable

from execution_v2.config_types import EntryIntent, PositionState, StopMode


SCHEMA_VERSION = 2


class StateStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self._pragma()
        self._migrate()

    def _pragma(self) -> None:
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")

    def _migrate(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        cur.execute("SELECT value FROM meta WHERE key='schema_version';")
        row = cur.fetchone()

        if row is None:
            cur.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version', ?);",
                (str(SCHEMA_VERSION),),
            )
            self._create_schema_v1()
        else:
            v = int(row["value"])
            if v == 1:
                self._migrate_v1_to_v2()
                cur.execute(
                    "UPDATE meta SET value=? WHERE key='schema_version';",
                    (str(SCHEMA_VERSION),),
                )
            elif v != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported schema_version {v}; expected {SCHEMA_VERSION}"
                )

    def _create_schema_v1(self) -> None:
        cur = self.conn.cursor()

        # Candidates: validity and per-symbol plan metadata (minimal for now)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS candidates (
              symbol TEXT PRIMARY KEY,
              first_seen_ts REAL NOT NULL,
              expires_ts REAL NOT NULL,
              pivot_level REAL,
              notes TEXT
            );
            """
        )

        # Entry intents: scheduled entry after BOH confirmation (randomized timing)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entry_intents (
              symbol TEXT PRIMARY KEY,
              pivot_level REAL NOT NULL,
              boh_confirmed_at REAL NOT NULL,
              scheduled_entry_at REAL NOT NULL,
              size_shares INTEGER NOT NULL,
              created_ts REAL NOT NULL
            );
            """
        )

        # Positions: behavioral risk state + trim flags
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
              symbol TEXT PRIMARY KEY,
              size_shares INTEGER NOT NULL,
              avg_price REAL NOT NULL,
              pivot_level REAL NOT NULL
	      r1_level REAL NOT NULL,
	      r2_level REAL NOT NULL,
              stop_mode TEXT NOT NULL,
              last_update_ts REAL NOT NULL,
              last_boh_level REAL,
              invalidation_count INTEGER NOT NULL,
              trimmed_r1 INTEGER NOT NULL,
              trimmed_r2 INTEGER NOT NULL
            );
            """
        )

        # Idempotency: record external order ids we have already issued/handled
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS order_ledger (
              idempotency_key TEXT PRIMARY KEY,
              symbol TEXT NOT NULL,
              side TEXT NOT NULL,
              qty INTEGER NOT NULL,
              created_ts REAL NOT NULL,
              external_order_id  TEXT
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trim_intents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL,
              pct REAL NOT NULL,
              reason TEXT NOT NULL,
              created_ts REAL NOT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trim_intents_sym ON trim_intents(symbol);")


        # Helpful indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_candidates_expires ON candidates(expires_ts);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_intents_sched ON entry_intents(scheduled_entry_at);")

    # -------------------------
    # Candidates
    # -------------------------
    def _migrate_v1_to_v2(self) -> None:
        """
        Schema v2 changes:
        - positions: add pivot_level, r1_level, r2_level
        - add trim_intents table
        """
        cur = self.conn.cursor()

        cur.execute("PRAGMA table_info(positions);")
        cols = {r["name"] for r in cur.fetchall()}

        def add_col(name: str, ddl: str) -> None:
            if name not in cols:
                cur.execute(f"ALTER TABLE positions ADD COLUMN {ddl};")

        add_col("pivot_level", "pivot_level REAL NOT NULL DEFAULT 0")
        add_col("r1_level", "r1_level REAL NOT NULL DEFAULT 0")
        add_col("r2_level", "r2_level REAL NOT NULL DEFAULT 0")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trim_intents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              symbol TEXT NOT NULL,
              pct REAL NOT NULL,
              reason TEXT NOT NULL,
              created_ts REAL NOT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trim_intents_sym ON trim_intents(symbol);")

    def upsert_candidate(
        self, symbol: str, first_seen_ts: float, expires_ts: float, pivot_level: Optional[float] = None, notes: str = ""
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO candidates(symbol, first_seen_ts, expires_ts, pivot_level, notes)
            VALUES(?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
              expires_ts=excluded.expires_ts,
              pivot_level=COALESCE(excluded.pivot_level, candidates.pivot_level),
              notes=excluded.notes
            ;
            """,
            (symbol, first_seen_ts, expires_ts, pivot_level, notes),
        )

    def list_active_candidates(self, now_ts: float) -> list[str]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT symbol FROM candidates WHERE expires_ts >= ? ORDER BY symbol;",
            (now_ts,),
        )
        return [r["symbol"] for r in cur.fetchall()]

    # -------------------------
    # Entry intents
    # -------------------------

    def put_entry_intent(self, intent: EntryIntent) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO entry_intents(symbol, pivot_level, boh_confirmed_at, scheduled_entry_at, size_shares, created_ts)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
              pivot_level=excluded.pivot_level,
              boh_confirmed_at=excluded.boh_confirmed_at,
              scheduled_entry_at=excluded.scheduled_entry_at,
              size_shares=excluded.size_shares
            ;
            """,
            (
                intent.symbol,
                intent.pivot_level,
                intent.boh_confirmed_at,
                intent.scheduled_entry_at,
                intent.size_shares,
                time.time(),
            ),
        )

    def get_entry_intent(self, symbol: str) -> Optional[EntryIntent]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT symbol,pivot_level,boh_confirmed_at,scheduled_entry_at,size_shares FROM entry_intents WHERE symbol=?;",
            (symbol,),
        )
        r = cur.fetchone()
        if r is None:
            return None
        return EntryIntent(
            symbol=r["symbol"],
            pivot_level=float(r["pivot_level"]),
            boh_confirmed_at=float(r["boh_confirmed_at"]),
            scheduled_entry_at=float(r["scheduled_entry_at"]),
            size_shares=int(r["size_shares"]),
        )

    def pop_due_entry_intents(self, now_ts: float) -> list[EntryIntent]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT symbol,pivot_level,boh_confirmed_at,scheduled_entry_at,size_shares
            FROM entry_intents
            WHERE scheduled_entry_at <= ?
            ORDER BY scheduled_entry_at ASC;
            """,
            (now_ts,),
        )
        rows = cur.fetchall()
        intents: list[EntryIntent] = []
        for r in rows:
            intents.append(
                EntryIntent(
                    symbol=r["symbol"],
                    pivot_level=float(r["pivot_level"]),
                    boh_confirmed_at=float(r["boh_confirmed_at"]),
                    scheduled_entry_at=float(r["scheduled_entry_at"]),
                    size_shares=int(r["size_shares"]),
                )
            )
        # Delete due intents after reading (single-writer assumption)
        cur.execute("DELETE FROM entry_intents WHERE scheduled_entry_at <= ?;", (now_ts,))
        return intents

    # -------------------------
    # Positions
    # -------------------------

    def upsert_position(self, ps: PositionState) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO positions(
              symbol,size_shares,avg_price,pivot_level,r1_level,r2_level,stop_mode,last_update_ts,last_boh_level,invalidation_count,trimmed_r1,trimmed_r2
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
              size_shares=excluded.size_shares,
              avg_price=excluded.avg_price,
              pivot_level=excluded.pivot_level,
              r1_level=excluded.r1_level,
              r2_level=excluded.r2_level,
              stop_mode=excluded.stop_mode,
              last_update_ts=excluded.last_update_ts,
              last_boh_level=excluded.last_boh_level,
              invalidation_count=excluded.invalidation_count,
              trimmed_r1=excluded.trimmed_r1,
              trimmed_r2=excluded.trimmed_r2
            ;
            """,
            (
                ps.symbol,
                ps.size_shares,
                ps.avg_price,
                ps.pivot_level,
                ps.r1_level,
                ps.r2_level,
                ps.stop_mode.value,
                ps.last_update_ts,
                ps.last_boh_level,
                ps.invalidation_count,
                1 if ps.trimmed_r1 else 0,
                1 if ps.trimmed_r2 else 0,
            ),
        )

    def get_position(self, symbol: str) -> Optional[PositionState]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM positions WHERE symbol=?;", (symbol,))
        r = cur.fetchone()
        if r is None:
            return None
        return PositionState(
            symbol=r["symbol"],
            size_shares=int(r["size_shares"]),
            avg_price=float(r["avg_price"]),
            pivot_level=float(r["pivot_level"]),
	    r1_level=float(r["r1_level"]),
	    r2_level=float(r["r2_level"]), 
            stop_mode=StopMode(r["stop_mode"]),
            last_update_ts=float(r["last_update_ts"]),
            last_boh_level=(float(r["last_boh_level"]) if r["last_boh_level"] is not None else None),
            invalidation_count=int(r["invalidation_count"]),
            trimmed_r1=bool(int(r["trimmed_r1"])),
            trimmed_r2=bool(int(r["trimmed_r2"])),
        )

    def list_positions(self) -> list[PositionState]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM positions ORDER BY symbol;")
        out: list[PositionState] = []
        for r in cur.fetchall():
            out.append(
                PositionState(
                    symbol=r["symbol"],
                    size_shares=int(r["size_shares"]),
                    avg_price=float(r["avg_price"]),
                    pivot_level=float(r["pivot_level"]),
                    r1_level=float(r["r1_level"]),
                    r2_level=float(r["r2_level"]),
                    stop_mode=StopMode(r["stop_mode"]),
                    last_update_ts=float(r["last_update_ts"]),
                    last_boh_level=(float(r["last_boh_level"]) if r["last_boh_level"] is not None else None),
                    invalidation_count=int(r["invalidation_count"]),
                    trimmed_r1=bool(int(r["trimmed_r1"])),
                    trimmed_r2=bool(int(r["trimmed_r2"])),
                )
            )
        return out

    def delete_position(self, symbol: str) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM positions WHERE symbol=?;", (symbol,))

    def update_stop_mode(self, symbol: str, mode: StopMode) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE positions SET stop_mode=?, last_update_ts=? WHERE symbol=?;",
            (mode.value, time.time(), symbol),
        )

    def mark_trimmed(self, symbol: str, which: str) -> None:
        if which not in ("r1", "r2"):
            raise ValueError("which must be 'r1' or 'r2'")
        col = "trimmed_r1" if which == "r1" else "trimmed_r2"
        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE positions SET {col}=1, last_update_ts=? WHERE symbol=?;",
            (time.time(), symbol),
        )

    def create_trim_intent(self, symbol: str, pct: float, reason: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO trim_intents(symbol,pct,reason,created_ts) VALUES(?,?,?,?);",
            (symbol, float(pct), str(reason), time.time()),
        )
    # -------------------------
    # Order idempotency
    # -------------------------

    def record_order_once(
        self,
        idempotency_key: str,
        symbol: str,
        side: str,
        qty: int,
        external_order_id: Optional[str] = None,
    ) -> bool:
        """
        Returns True if recorded (first time); False if the key already exists.
        """
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO order_ledger(idempotency_key,symbol,side,qty,created_ts,external_order_id)
                VALUES(?,?,?,?,?,?);
                """,
                (idempotency_key, symbol, side, int(qty), time.time(), external_order_id),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def update_external_order_id(self, idempotency_key: str, external_order_id: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE order_ledger SET external_order_id=? WHERE idempotency_key=?;",
            (external_order_id, idempotency_key),
        )


def default_db_path(repo_root: str) -> str:
    # Keep state in-repo under /data for simple deployment + backup.
    data_dir = os.path.join(repo_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "execution_v2_state.sqlite3")
