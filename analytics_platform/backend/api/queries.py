from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

S2_STRATEGY_ID = "S2_LETF_ORB_AGGRO"
S1_STRATEGY_ID = "S1_AVWAP_CORE"


def _rows(conn, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    frame = conn.execute(sql, params or []).fetchdf()
    if frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _date_clause(column: str, start: str | None, end: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append(f"{column} >= ?")
        params.append(start)
    if end:
        clauses.append(f"{column} <= ?")
        params.append(end)
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def get_freshness(conn) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT source_name, source_glob, file_count, row_count, latest_mtime_utc, parse_status, last_error
        FROM freshness_health
        ORDER BY source_name
        """,
    )


def get_overview(conn, start: str | None, end: str | None) -> dict[str, Any]:
    where, params = _date_clause("ny_date", start, end)
    totals = _rows(
        conn,
        f"""
        SELECT
            COUNT(*) AS cycle_count,
            COALESCE(SUM(intent_count), 0) AS intent_count,
            COALESCE(SUM(entry_intents_created_count), 0) AS created_count,
            COALESCE(SUM(accepted_count), 0) AS accepted_count,
            COALESCE(SUM(rejected_count), 0) AS rejected_count,
            COALESCE(SUM(gate_block_count), 0) AS gate_block_count
        FROM decision_cycles
        {where}
        """,
        params,
    )
    strategy_intents = _rows(
        conn,
        f"""
        SELECT strategy_id, COUNT(*) AS intent_rows, COALESCE(SUM(qty), 0) AS total_qty
        FROM decision_intents
        {where}
        GROUP BY strategy_id
        ORDER BY intent_rows DESC, strategy_id
        """,
        params,
    )
    s2_quality = _rows(
        conn,
        """
        SELECT
            COUNT(*) AS signal_rows,
            COALESCE(SUM(CASE WHEN eligible THEN 1 ELSE 0 END), 0) AS eligible_rows,
            COALESCE(SUM(CASE WHEN selected THEN 1 ELSE 0 END), 0) AS selected_rows,
            AVG(score) AS avg_score
        FROM strategy_signals
        WHERE strategy_id = ?
        """,
        [S2_STRATEGY_ID],
    )
    rejection_mix = _rows(
        conn,
        f"""
        SELECT reason_code, COALESCE(SUM(rejected_count), 0) AS rejected_count
        FROM entry_rejections
        {where}
        GROUP BY reason_code
        ORDER BY rejected_count DESC, reason_code
        """,
        params,
    )
    return {
        "totals": totals[0] if totals else {},
        "strategy_intents": strategy_intents,
        "s2_signal_quality": s2_quality[0] if s2_quality else {},
        "rejection_mix": rejection_mix,
    }


def get_strategies_compare(conn, start: str | None, end: str | None) -> dict[str, Any]:
    where, params = _date_clause("ny_date", start, end)
    intent_compare = _rows(
        conn,
        f"""
        SELECT strategy_id,
               COUNT(*) AS intent_rows,
               COUNT(DISTINCT symbol) AS unique_symbols,
               COALESCE(SUM(qty), 0) AS total_qty
        FROM decision_intents
        {where}
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
        params,
    )
    s2_reasons = _rows(
        conn,
        """
        SELECT reason_code, COUNT(*) AS reason_count
        FROM (
            SELECT UNNEST(json_extract_string(reason_codes_json, '$[*]')) AS reason_code
            FROM strategy_signals
            WHERE strategy_id = ?
        )
        GROUP BY reason_code
        ORDER BY reason_count DESC, reason_code
        """,
        [S2_STRATEGY_ID],
    )
    s2_signal_metrics = _rows(
        conn,
        """
        SELECT
            COUNT(*) AS signal_rows,
            COALESCE(SUM(CASE WHEN eligible THEN 1 ELSE 0 END), 0) AS eligible_rows,
            COALESCE(SUM(CASE WHEN selected THEN 1 ELSE 0 END), 0) AS selected_rows,
            AVG(score) AS avg_score
        FROM strategy_signals
        WHERE strategy_id = ?
        """,
        [S2_STRATEGY_ID],
    )
    return {
        "intent_compare": intent_compare,
        "s2_signal_metrics": s2_signal_metrics[0] if s2_signal_metrics else {},
        "s2_reason_mix": s2_reasons,
        "notes": [
            "AVWAP signal-level rows are not emitted in strategy_signals; compare uses decision_intents for AVWAP.",
            "S2 compare includes signal-quality metrics from STRATEGY_SIGNALS.",
        ],
    }


def get_decisions_timeseries(conn, start: str | None, end: str | None, granularity: str = "day") -> dict[str, Any]:
    if granularity != "day":
        granularity = "day"
    where, params = _date_clause("ny_date", start, end)
    rows = _rows(
        conn,
        f"""
        SELECT ny_date,
               COUNT(*) AS cycle_count,
               COALESCE(SUM(intent_count), 0) AS intent_count,
               COALESCE(SUM(entry_intents_created_count), 0) AS created_count,
               COALESCE(SUM(accepted_count), 0) AS accepted_count,
               COALESCE(SUM(rejected_count), 0) AS rejected_count,
               COALESCE(SUM(gate_block_count), 0) AS gate_blocks
        FROM decision_cycles
        {where}
        GROUP BY ny_date
        ORDER BY ny_date
        """,
        params,
    )
    return {"granularity": granularity, "points": rows}


def get_s2_signals(
    conn,
    *,
    date: str | None,
    symbol: str | None,
    eligible: bool | None,
    selected: bool | None,
    reason_code: str | None,
    limit: int,
) -> dict[str, Any]:
    clauses = ["strategy_id = ?"]
    params: list[Any] = [S2_STRATEGY_ID]
    if date:
        clauses.append("asof_date = ?")
        params.append(date)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if eligible is not None:
        clauses.append("eligible = ?")
        params.append(bool(eligible))
    if selected is not None:
        clauses.append("selected = ?")
        params.append(bool(selected))
    if reason_code:
        clauses.append("reason_codes_json LIKE ?")
        params.append(f"%{reason_code}%")

    where = " WHERE " + " AND ".join(clauses)
    rows = _rows(
        conn,
        f"""
        SELECT run_id, asof_date, strategy_id, symbol, complex, eligible, selected, score,
               reason_codes_json, gates_json, metrics_json
        FROM strategy_signals
        {where}
        ORDER BY asof_date DESC, score DESC NULLS LAST, symbol
        LIMIT ?
        """,
        params + [max(1, min(limit, 5000))],
    )
    return {"count": len(rows), "rows": rows}


def get_risk_controls(conn, start: str | None, end: str | None) -> dict[str, Any]:
    where, params = _date_clause("ny_date", start, end)
    controls = _rows(
        conn,
        f"""
        SELECT source_type, ny_date, as_of_utc, regime_id, risk_multiplier, max_positions,
               max_gross_exposure, per_position_cap, throttle_reason
        FROM risk_controls_daily
        {where}
        ORDER BY ny_date, as_of_utc
        """,
        params,
    )
    regimes = _rows(
        conn,
        f"""
        SELECT ny_date, as_of_utc, regime_id, regime_label, reason_codes_json
        FROM regime_daily
        {where}
        ORDER BY ny_date, as_of_utc
        """,
        params,
    )
    return {"risk_controls": controls, "regimes": regimes}


def list_backtest_runs(conn) -> list[dict[str, Any]]:
    return _rows(
        conn,
        """
        SELECT run_id, suite, variant, summary_path, summary_mtime_utc,
               has_equity_curve, has_trades, has_scan_diagnostics
        FROM backtest_runs
        ORDER BY summary_mtime_utc DESC, run_id
        """,
    )


def get_backtest_run(conn, run_id: str) -> dict[str, Any] | None:
    runs = _rows(
        conn,
        """
        SELECT run_id, suite, variant, summary_path, summary_mtime_utc,
               has_equity_curve, has_trades, has_scan_diagnostics, summary_json
        FROM backtest_runs
        WHERE run_id = ?
        """,
        [run_id],
    )
    if not runs:
        return None
    run = runs[0]
    metrics = _rows(
        conn,
        """
        SELECT metric_name, metric_value
        FROM backtest_metrics
        WHERE run_id = ?
        ORDER BY metric_name
        """,
        [run_id],
    )
    equity = _rows(
        conn,
        """
        SELECT point_index, x_value, equity
        FROM backtest_equity
        WHERE run_id = ?
        ORDER BY point_index
        LIMIT 1200
        """,
        [run_id],
    )
    return {"run": run, "metrics": metrics, "equity_curve": equity}


EXPORT_TABLES = {
    "decision_cycles": ("decision_cycles", "ny_date"),
    "decision_intents": ("decision_intents", "ny_date"),
    "entry_rejections": ("entry_rejections", "ny_date"),
    "strategy_signals": ("strategy_signals", "asof_date"),
    "risk_controls": ("risk_controls_daily", "ny_date"),
    "regimes": ("regime_daily", "ny_date"),
    "backtest_runs": ("backtest_runs", None),
    "backtest_metrics": ("backtest_metrics", None),
    "freshness": ("freshness_health", None),
    "raec_rebalance_events": ("raec_rebalance_events", "ny_date"),
    "raec_allocations": ("raec_allocations", "ny_date"),
    "raec_intents": ("raec_intents", "ny_date"),
    "raec_coordinator_runs": ("raec_coordinator_runs", "ny_date"),
    "execution_slippage": ("execution_slippage", "date_ny"),
    "portfolio_snapshots": ("portfolio_snapshots", "date_ny"),
    "portfolio_positions": ("portfolio_positions", "date_ny"),
}


def export_dataset_csv(
    conn,
    *,
    dataset: str,
    start: str | None,
    end: str | None,
    limit: int = 10000,
) -> tuple[str, str]:
    if dataset not in EXPORT_TABLES:
        raise KeyError(dataset)
    table, date_col = EXPORT_TABLES[dataset]

    clauses: list[str] = []
    params: list[Any] = []
    if date_col and start:
        clauses.append(f"{date_col} >= ?")
        params.append(start)
    if date_col and end:
        clauses.append(f"{date_col} <= ?")
        params.append(end)

    where = ""
    if clauses:
        where = " WHERE " + " AND ".join(clauses)

    frame = conn.execute(f"SELECT * FROM {table}{where} LIMIT ?", params + [max(1, min(limit, 100000))]).fetchdf()
    buffer = StringIO()
    frame.to_csv(buffer, index=False, quoting=csv.QUOTE_MINIMAL)
    return f"{dataset}.csv", buffer.getvalue()


# ---------------------------------------------------------------------------
# RAEC Dashboard
# ---------------------------------------------------------------------------

def _raec_where(start: str | None, end: str | None, strategy_id: str | None) -> tuple[str, list[Any]]:
    """Build WHERE clause for RAEC queries with optional date range + strategy filter."""
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("ny_date >= ?")
        params.append(start)
    if end:
        clauses.append("ny_date <= ?")
        params.append(end)
    if strategy_id:
        clauses.append("strategy_id = ?")
        params.append(strategy_id)
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def get_raec_dashboard(conn, start: str | None, end: str | None, strategy_id: str | None = None) -> dict[str, Any]:
    where, params = _raec_where(start, end, strategy_id)

    by_strategy = _rows(
        conn,
        f"""
        SELECT
            strategy_id,
            COUNT(*) AS events,
            COALESCE(SUM(CASE WHEN should_rebalance THEN 1 ELSE 0 END), 0) AS rebalance_count,
            MAX(ny_date) AS last_eval_date,
            LAST(regime ORDER BY ny_date, ts_utc) AS latest_regime,
            LAST(portfolio_vol_target ORDER BY ny_date, ts_utc) AS portfolio_vol_target
        FROM raec_rebalance_events
        {where}
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
        params,
    )

    total_events = sum(r["events"] for r in by_strategy)
    total_rebalances = sum(r["rebalance_count"] for r in by_strategy)

    regime_history = _rows(
        conn,
        f"""
        SELECT ny_date, strategy_id, regime
        FROM raec_rebalance_events
        {where}
        ORDER BY ny_date, ts_utc
        """,
        params,
    )

    # Latest allocations per strategy: most recent ny_date for each strategy
    alloc_where_parts: list[str] = []
    alloc_params: list[Any] = []
    if strategy_id:
        alloc_where_parts.append("strategy_id = ?")
        alloc_params.append(strategy_id)
    if start:
        alloc_where_parts.append("ny_date >= ?")
        alloc_params.append(start)
    if end:
        alloc_where_parts.append("ny_date <= ?")
        alloc_params.append(end)
    alloc_where = (" WHERE " + " AND ".join(alloc_where_parts)) if alloc_where_parts else ""

    allocation_snapshots = _rows(
        conn,
        f"""
        SELECT a.ny_date, a.strategy_id, a.alloc_type, a.symbol, a.weight_pct
        FROM raec_allocations a
        INNER JOIN (
            SELECT strategy_id, MAX(ny_date) AS max_date
            FROM raec_allocations
            {alloc_where}
            GROUP BY strategy_id
        ) latest ON a.strategy_id = latest.strategy_id AND a.ny_date = latest.max_date
        ORDER BY a.strategy_id, a.alloc_type, a.symbol
        """,
        alloc_params,
    )

    return {
        "total_events": total_events,
        "total_rebalances": total_rebalances,
        "by_strategy": by_strategy,
        "regime_history": regime_history,
        "allocation_snapshots": allocation_snapshots,
    }


# ---------------------------------------------------------------------------
# Journal (unified trade intent log)
# ---------------------------------------------------------------------------

def get_journal(
    conn,
    *,
    start: str | None,
    end: str | None,
    strategy_id: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    # Build shared filter clauses (applied to the CTE)
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("j.ny_date >= ?")
        params.append(start)
    if end:
        clauses.append("j.ny_date <= ?")
        params.append(end)
    if strategy_id:
        clauses.append("j.strategy_id = ?")
        params.append(strategy_id)
    if symbol:
        clauses.append("j.symbol = ?")
        params.append(symbol.upper())
    if side:
        clauses.append("j.side = ?")
        params.append(side.upper())

    outer_where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    safe_limit = max(1, min(limit, 5000))

    rows = _rows(
        conn,
        f"""
        WITH journal AS (
            SELECT
                ri.ny_date,
                ri.ts_utc,
                ri.strategy_id,
                ri.symbol,
                ri.side,
                ri.delta_pct,
                ri.target_pct,
                ri.current_pct,
                re.regime,
                'raec' AS source
            FROM raec_intents ri
            LEFT JOIN raec_rebalance_events re
                ON ri.ny_date = re.ny_date AND ri.strategy_id = re.strategy_id

            UNION ALL

            SELECT
                di.ny_date,
                di.ts_utc,
                di.strategy_id,
                di.symbol,
                di.side,
                NULL AS delta_pct,
                NULL AS target_pct,
                NULL AS current_pct,
                COALESCE(CAST(rd.regime_label AS VARCHAR), rd.regime_id) AS regime,
                'decision' AS source
            FROM decision_intents di
            LEFT JOIN regime_daily rd ON di.ny_date = rd.ny_date
        )
        SELECT j.*
        FROM journal j
        {outer_where}
        ORDER BY j.ny_date DESC, j.ts_utc DESC
        LIMIT ?
        """,
        params + [safe_limit],
    )
    return {"count": len(rows), "rows": rows}


# ---------------------------------------------------------------------------
# RAEC Readiness
# ---------------------------------------------------------------------------

_RAEC_STRATEGY_IDS = [
    "RAEC_401K_V1",
    "RAEC_401K_V2",
    "RAEC_401K_V3",
    "RAEC_401K_V4",
    "RAEC_401K_V5",
    "RAEC_401K_COORD",
]

_BOOK_ID = "SCHWAB_401K_MANUAL"


def get_raec_readiness(conn, repo_root: Path) -> dict[str, Any]:
    from datetime import date

    today = date.today().isoformat()
    strategies: list[dict[str, Any]] = []

    for sid in _RAEC_STRATEGY_IDS:
        state_file = repo_root / "state" / "strategies" / _BOOK_ID / f"{sid}.json"
        warnings: list[str] = []
        state_data: dict[str, Any] = {}

        if state_file.exists():
            try:
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                warnings.append("state_file_corrupt")
        else:
            warnings.append("missing_state_file")

        last_eval = state_data.get("last_eval_date")
        last_regime = state_data.get("last_regime")
        last_allocs = state_data.get("last_known_allocations")

        if last_eval and last_eval < today:
            warnings.append("stale_eval")
        if not last_allocs:
            warnings.append("no_allocations")

        # Count ledger files for today
        ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / sid
        today_ledger_count = 0
        if ledger_dir.exists():
            today_ledger_count = sum(
                1 for f in ledger_dir.iterdir()
                if f.name.startswith(today) and f.suffix == ".jsonl"
            )

        strategies.append({
            "strategy_id": sid,
            "state_file_exists": state_file.exists(),
            "last_eval_date": last_eval,
            "last_regime": last_regime,
            "last_known_allocations": last_allocs,
            "today_ledger_count": today_ledger_count,
            "warnings": warnings,
        })

    coord = next((s for s in strategies if s["strategy_id"] == "RAEC_401K_COORD"), None)
    return {
        "strategies": strategies,
        "coordinator": coord,
    }


# ---------------------------------------------------------------------------
# RAEC P&L / Activity summary
# ---------------------------------------------------------------------------

def get_pnl(conn, start: str | None, end: str | None, strategy_id: str | None = None) -> dict[str, Any]:
    where, params = _raec_where(start, end, strategy_id)

    by_strategy = _rows(
        conn,
        f"""
        SELECT
            strategy_id,
            COUNT(*) AS eval_count,
            COALESCE(SUM(CASE WHEN should_rebalance THEN 1 ELSE 0 END), 0) AS rebalance_count,
            COUNT(DISTINCT regime) AS regime_changes
        FROM raec_rebalance_events
        {where}
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
        params,
    )

    # Allocation drift: difference between total target weight and total current weight per day
    drift_where, drift_params = _raec_where(start, end, strategy_id)
    drift = _rows(
        conn,
        f"""
        SELECT
            ny_date,
            strategy_id,
            SUM(CASE WHEN alloc_type = 'target' THEN weight_pct ELSE 0 END) AS target_total,
            SUM(CASE WHEN alloc_type = 'current' THEN weight_pct ELSE 0 END) AS current_total,
            SUM(CASE WHEN alloc_type = 'target' THEN weight_pct ELSE 0 END)
              - SUM(CASE WHEN alloc_type = 'current' THEN weight_pct ELSE 0 END) AS drift
        FROM raec_allocations
        {drift_where}
        GROUP BY ny_date, strategy_id
        ORDER BY ny_date, strategy_id
        """,
        drift_params,
    )

    return {
        "by_strategy": by_strategy,
        "allocation_drift": drift,
    }


# ---------------------------------------------------------------------------
# Slippage Dashboard
# ---------------------------------------------------------------------------

def _slippage_where(
    start: str | None, end: str | None, strategy_id: str | None
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("date_ny >= ?")
        params.append(start)
    if end:
        clauses.append("date_ny <= ?")
        params.append(end)
    if strategy_id:
        clauses.append("strategy_id = ?")
        params.append(strategy_id)
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def get_slippage_dashboard(
    conn, start: str | None, end: str | None, strategy_id: str | None = None
) -> dict[str, Any]:
    where, params = _slippage_where(start, end, strategy_id)

    summary = _rows(
        conn,
        f"""
        SELECT
            COUNT(*) AS total,
            AVG(slippage_bps) AS mean_bps,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY slippage_bps) AS median_bps,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY slippage_bps) AS p95_bps
        FROM execution_slippage
        {where}
        """,
        params,
    )

    by_bucket = _rows(
        conn,
        f"""
        SELECT liquidity_bucket,
               COUNT(*) AS count,
               AVG(slippage_bps) AS mean_bps,
               MIN(slippage_bps) AS min_bps,
               MAX(slippage_bps) AS max_bps
        FROM execution_slippage
        {where}
        GROUP BY liquidity_bucket
        ORDER BY liquidity_bucket
        """,
        params,
    )

    by_time = _rows(
        conn,
        f"""
        SELECT time_of_day_bucket,
               COUNT(*) AS count,
               AVG(slippage_bps) AS mean_bps,
               MIN(slippage_bps) AS min_bps,
               MAX(slippage_bps) AS max_bps
        FROM execution_slippage
        {where}
        GROUP BY time_of_day_bucket
        ORDER BY time_of_day_bucket
        """,
        params,
    )

    by_symbol = _rows(
        conn,
        f"""
        SELECT symbol,
               COUNT(*) AS count,
               AVG(slippage_bps) AS mean_bps
        FROM execution_slippage
        {where}
        GROUP BY symbol
        ORDER BY ABS(AVG(slippage_bps)) DESC
        LIMIT 10
        """,
        params,
    )

    trend = _rows(
        conn,
        f"""
        SELECT date_ny,
               AVG(slippage_bps) AS mean_bps,
               COUNT(*) AS count
        FROM execution_slippage
        {where}
        GROUP BY date_ny
        ORDER BY date_ny
        """,
        params,
    )

    return {
        "summary": summary[0] if summary else {},
        "by_bucket": by_bucket,
        "by_time": by_time,
        "by_symbol": by_symbol,
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# Portfolio Overview / Positions / History
# ---------------------------------------------------------------------------


def _portfolio_date_clause(
    column: str, start: str | None, end: str | None
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append(f"{column} >= ?")
        params.append(start)
    if end:
        clauses.append(f"{column} <= ?")
        params.append(end)
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def get_portfolio_overview(
    conn, start: str | None = None, end: str | None = None
) -> dict[str, Any]:
    # latest snapshot
    latest_rows = _rows(
        conn,
        """
        SELECT date_ny, capital_total, capital_cash, capital_invested,
               gross_exposure, net_exposure, realized_pnl, unrealized_pnl, fees_today
        FROM portfolio_snapshots
        ORDER BY date_ny DESC
        LIMIT 1
        """,
    )
    latest = latest_rows[0] if latest_rows else {}
    latest_date = latest.get("date_ny")

    # positions for latest date with weight_pct
    positions: list[dict[str, Any]] = []
    if latest_date:
        positions = _rows(
            conn,
            """
            SELECT strategy_id, symbol, qty, avg_price, mark_price, notional,
                   notional / SUM(notional) OVER () * 100 AS weight_pct
            FROM portfolio_positions
            WHERE date_ny = ?
            ORDER BY notional DESC
            """,
            [latest_date],
        )

    # exposure by strategy
    exposure_by_strategy: list[dict[str, Any]] = []
    if latest_date:
        exposure_by_strategy = _rows(
            conn,
            """
            SELECT strategy_id, SUM(notional) AS notional
            FROM portfolio_positions
            WHERE date_ny = ?
            GROUP BY strategy_id
            ORDER BY strategy_id
            """,
            [latest_date],
        )

    # history time series
    where, params = _portfolio_date_clause("date_ny", start, end)
    history = _rows(
        conn,
        f"""
        SELECT date_ny, capital_total, gross_exposure, net_exposure, realized_pnl
        FROM portfolio_snapshots
        {where}
        ORDER BY date_ny ASC
        """,
        params,
    )

    return {
        "latest": latest,
        "positions": positions,
        "exposure_by_strategy": exposure_by_strategy,
        "history": history,
    }


def get_portfolio_positions(
    conn, date: str | None = None
) -> dict[str, Any]:
    # resolve date
    if date is None:
        date_rows = _rows(
            conn,
            "SELECT MAX(date_ny) AS date_ny FROM portfolio_positions",
        )
        date = date_rows[0]["date_ny"] if date_rows and date_rows[0]["date_ny"] else None
    if date is None:
        return {"date_ny": None, "total_notional": 0, "by_strategy": []}

    # all positions for this date
    rows = _rows(
        conn,
        """
        SELECT strategy_id, symbol, qty, avg_price, mark_price, notional
        FROM portfolio_positions
        WHERE date_ny = ?
        ORDER BY strategy_id, notional DESC
        """,
        [date],
    )

    total_notional = sum(r["notional"] or 0 for r in rows)

    # group by strategy_id
    by_strategy: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        sid = r["strategy_id"]
        r["weight_pct"] = (r["notional"] / total_notional * 100) if total_notional else 0
        by_strategy.setdefault(sid, []).append(r)

    return {
        "date_ny": date,
        "total_notional": total_notional,
        "by_strategy": [
            {"strategy_id": sid, "positions": positions}
            for sid, positions in sorted(by_strategy.items())
        ],
    }


def get_portfolio_history(
    conn, start: str | None, end: str | None
) -> dict[str, Any]:
    where, params = _portfolio_date_clause("date_ny", start, end)
    rows = _rows(
        conn,
        f"""
        SELECT date_ny, capital_total, capital_cash, gross_exposure,
               net_exposure, realized_pnl, unrealized_pnl
        FROM portfolio_snapshots
        {where}
        ORDER BY date_ny ASC
        """,
        params,
    )
    return {"points": rows}


def get_strategy_matrix(conn) -> dict[str, Any]:
    # S1/S2 stats from decision_intents
    decision_stats = _rows(
        conn,
        """
        SELECT strategy_id,
               COUNT(*) AS trade_count,
               COUNT(DISTINCT symbol) AS unique_symbols
        FROM decision_intents
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
    )

    # RAEC stats: rebalance count from raec_rebalance_events
    raec_rebalance_stats = _rows(
        conn,
        """
        SELECT strategy_id,
               COUNT(*) AS rebalance_count,
               LAST(regime ORDER BY ny_date, ts_utc) AS latest_regime
        FROM raec_rebalance_events
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
    )

    # RAEC unique symbols from raec_intents
    raec_symbol_stats = _rows(
        conn,
        """
        SELECT strategy_id,
               COUNT(DISTINCT symbol) AS unique_symbols
        FROM raec_intents
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
    )
    raec_symbol_map = {r["strategy_id"]: r["unique_symbols"] for r in raec_symbol_stats}

    # Latest regime for S1/S2
    latest_regime_rows = _rows(
        conn,
        """
        SELECT regime_id, regime_label
        FROM regime_daily
        ORDER BY ny_date DESC, as_of_utc DESC
        LIMIT 1
        """,
    )
    latest_regime = (
        (latest_regime_rows[0].get("regime_label") or latest_regime_rows[0]["regime_id"])
        if latest_regime_rows
        else None
    )

    # Exposure from portfolio_positions (latest date, grouped by strategy_id)
    exposure = _rows(
        conn,
        """
        SELECT strategy_id, SUM(notional) AS notional
        FROM portfolio_positions
        WHERE date_ny = (SELECT MAX(date_ny) FROM portfolio_positions)
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
    )
    exposure_map = {r["strategy_id"]: r["notional"] for r in exposure}

    # Build unified strategy list
    strategies: list[dict[str, Any]] = []

    for row in decision_stats:
        sid = row["strategy_id"]
        strategies.append({
            "strategy_id": sid,
            "source": "decision",
            "trade_count": row["trade_count"],
            "unique_symbols": row["unique_symbols"],
            "latest_regime": latest_regime,
            "exposure": exposure_map.get(sid),
        })

    for row in raec_rebalance_stats:
        sid = row["strategy_id"]
        strategies.append({
            "strategy_id": sid,
            "source": "raec",
            "rebalance_count": row["rebalance_count"],
            "unique_symbols": raec_symbol_map.get(sid, 0),
            "latest_regime": row["latest_regime"],
            "exposure": exposure_map.get(sid),
        })

    # Symbol overlap: symbols that appear in multiple strategies
    overlap = _rows(
        conn,
        """
        WITH all_symbols AS (
            SELECT strategy_id, symbol FROM decision_intents
            UNION
            SELECT strategy_id, symbol FROM raec_intents
            UNION
            SELECT strategy_id, symbol FROM portfolio_positions
            WHERE date_ny = (SELECT MAX(date_ny) FROM portfolio_positions)
        )
        SELECT symbol, LIST(DISTINCT strategy_id ORDER BY strategy_id) AS strategy_ids
        FROM all_symbols
        GROUP BY symbol
        HAVING COUNT(DISTINCT strategy_id) > 1
        ORDER BY symbol
        """,
    )

    # Ensure LIST columns are plain Python lists (DuckDB returns numpy arrays)
    for row in overlap:
        if "strategy_ids" in row and hasattr(row["strategy_ids"], "tolist"):
            row["strategy_ids"] = row["strategy_ids"].tolist()

    return {
        "strategies": strategies,
        "symbol_overlap": overlap,
    }


# ---------------------------------------------------------------------------
# Trade Analytics
# ---------------------------------------------------------------------------

def get_trade_analytics(
    conn, start: str | None, end: str | None, strategy_id: str | None = None
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("ny_date >= ?")
        params.append(start)
    if end:
        clauses.append("ny_date <= ?")
        params.append(end)
    if strategy_id:
        clauses.append("strategy_id = ?")
        params.append(strategy_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    combined_cte = f"""
        WITH combined AS (
            SELECT strategy_id, symbol, side, ny_date FROM decision_intents
            UNION ALL
            SELECT strategy_id, symbol, side, ny_date FROM raec_intents
        )
    """

    per_strategy = _rows(
        conn,
        f"""
        {combined_cte}
        SELECT strategy_id,
               COUNT(*) AS trade_count,
               COUNT(DISTINCT symbol) AS unique_symbols,
               SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) AS buys,
               SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS sells
        FROM combined
        {where}
        GROUP BY strategy_id
        ORDER BY trade_count DESC
        """,
        params,
    )

    daily_frequency = _rows(
        conn,
        f"""
        {combined_cte}
        SELECT ny_date, COUNT(*) AS count
        FROM combined
        {where}
        GROUP BY ny_date
        ORDER BY ny_date
        """,
        params,
    )

    symbol_concentration = _rows(
        conn,
        f"""
        {combined_cte}
        SELECT symbol, COUNT(*) AS count
        FROM combined
        {where}
        GROUP BY symbol
        ORDER BY count DESC
        LIMIT 15
        """,
        params,
    )

    return {
        "per_strategy": per_strategy,
        "daily_frequency": daily_frequency,
        "symbol_concentration": symbol_concentration,
    }
