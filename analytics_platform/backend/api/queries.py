from __future__ import annotations

import csv
from io import StringIO
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
        SELECT ny_date, as_of_utc, regime_id, reason_codes_json
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
