"""Trade log — DuckDB-backed CRUD for manual trade tracking.

Uses a **separate** DuckDB file (``trade_log.duckdb``) so the
analytics readmodel rebuild cycle doesn't destroy user data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradeLogStore:
    """Thread-safe CRUD for the trade log.

    Uses connection-per-request rather than a shared connection to avoid
    DuckDB's thread-safety limitations.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._ensure_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self._db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_log (
                id VARCHAR PRIMARY KEY,
                created_utc VARCHAR NOT NULL,
                updated_utc VARCHAR NOT NULL,
                entry_date VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                direction VARCHAR NOT NULL DEFAULT 'long',
                entry_price DOUBLE NOT NULL,
                qty INTEGER NOT NULL,
                stop_loss DOUBLE NOT NULL,
                target_r1 DOUBLE,
                target_r2 DOUBLE,
                strategy_source VARCHAR,
                scan_date VARCHAR,
                notes VARCHAR,
                exit_date VARCHAR,
                exit_price DOUBLE,
                exit_reason VARCHAR,
                risk_per_share DOUBLE NOT NULL,
                r_multiple DOUBLE,
                pnl_dollars DOUBLE,
                status VARCHAR NOT NULL DEFAULT 'open'
            );
            """)

    def create(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Insert a new open trade. Returns the created record."""
        trade_id = str(uuid.uuid4())[:12]
        now = _utc_now()

        entry_price = float(trade["entry_price"])
        stop_loss = float(trade["stop_loss"])
        direction = str(trade.get("direction", "long")).lower()
        if direction == "short":
            risk_per_share = abs(stop_loss - entry_price)
        else:
            risk_per_share = abs(entry_price - stop_loss)

        if risk_per_share <= 0:
            raise ValueError("risk_per_share must be positive (entry != stop)")

        row = {
            "id": trade_id,
            "created_utc": now,
            "updated_utc": now,
            "entry_date": str(trade["entry_date"]),
            "symbol": str(trade["symbol"]).upper(),
            "direction": direction,
            "entry_price": entry_price,
            "qty": int(trade["qty"]),
            "stop_loss": stop_loss,
            "target_r1": trade.get("target_r1"),
            "target_r2": trade.get("target_r2"),
            "strategy_source": trade.get("strategy_source"),
            "scan_date": trade.get("scan_date"),
            "notes": trade.get("notes"),
            "exit_date": None,
            "exit_price": None,
            "exit_reason": None,
            "risk_per_share": round(risk_per_share, 4),
            "r_multiple": None,
            "pnl_dollars": None,
            "status": "open",
        }

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO trade_log VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21
                )""",
                list(row.values()),
            )
        return row

    def update_exit(self, trade_id: str, exit_data: dict[str, Any]) -> dict[str, Any]:
        """Close a trade with exit data. Computes R-multiple and P&L."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trade_log WHERE id = ?", [trade_id]
            ).fetchall()
            if not rows:
                raise KeyError(f"Trade {trade_id} not found")
            cols = [d[0] for d in conn.description]
            trade = dict(zip(cols, rows[0]))

            exit_price = float(exit_data["exit_price"])
            entry_price = float(trade["entry_price"])
            risk_per_share = float(trade["risk_per_share"])
            qty = int(trade["qty"])
            direction = trade["direction"]

            if direction == "short":
                pnl_per_share = entry_price - exit_price
            else:
                pnl_per_share = exit_price - entry_price

            r_multiple = round(pnl_per_share / risk_per_share, 4) if risk_per_share > 0 else 0.0
            pnl_dollars = round(pnl_per_share * qty, 2)

            conn.execute(
                """UPDATE trade_log SET
                    exit_date = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    r_multiple = ?,
                    pnl_dollars = ?,
                    status = 'closed',
                    updated_utc = ?
                WHERE id = ?""",
                [
                    str(exit_data.get("exit_date", _utc_now()[:10])),
                    exit_price,
                    exit_data.get("exit_reason", "manual"),
                    r_multiple,
                    pnl_dollars,
                    _utc_now(),
                    trade_id,
                ],
            )

        return {**trade, "exit_price": exit_price, "exit_date": exit_data.get("exit_date"),
                "exit_reason": exit_data.get("exit_reason", "manual"),
                "r_multiple": r_multiple, "pnl_dollars": pnl_dollars, "status": "closed"}

    def list_trades(
        self,
        *,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List trades with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(min(max(limit, 1), 5000))

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM trade_log{where} ORDER BY created_utc DESC LIMIT ?",
                params,
            ).fetchall()
            cols = [d[0] for d in conn.description]
        return [dict(zip(cols, r)) for r in rows]

    def get_summary(self) -> dict[str, Any]:
        """Aggregate statistics across all trades."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'open') AS open_count,
                    COUNT(*) FILTER (WHERE status = 'closed') AS closed_count,
                    COUNT(*) FILTER (WHERE status = 'closed' AND pnl_dollars > 0) AS wins,
                    COUNT(*) FILTER (WHERE status = 'closed' AND pnl_dollars <= 0) AS losses,
                    AVG(r_multiple) FILTER (WHERE status = 'closed') AS avg_r,
                    SUM(pnl_dollars) FILTER (WHERE status = 'closed') AS total_pnl
                FROM trade_log
            """).fetchone()

        open_count, closed, wins, losses, avg_r, total_pnl = rows
        win_rate = (wins / closed * 100) if closed and closed > 0 else None

        return {
            "open_count": open_count or 0,
            "closed_count": closed or 0,
            "wins": wins or 0,
            "losses": losses or 0,
            "win_rate": round(win_rate, 1) if win_rate is not None else None,
            "avg_r_multiple": round(avg_r, 4) if avg_r is not None else None,
            "total_pnl": round(total_pnl, 2) if total_pnl is not None else 0.0,
        }

    def delete(self, trade_id: str) -> bool:
        """Delete a trade by ID. Returns True if deleted."""
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM trade_log WHERE id = ? RETURNING id", [trade_id]
            ).fetchone()
        return result is not None

    def close(self) -> None:
        pass  # no persistent connection to close
