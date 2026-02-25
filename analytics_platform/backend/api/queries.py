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


# ---------------------------------------------------------------------------
# Strategy Performance
# ---------------------------------------------------------------------------

def get_strategy_performance(
    conn,
    start: str | None = None,
    end: str | None = None,
    strategy_id: str | None = None,
    book_id: str | None = None,
) -> dict[str, Any]:
    import math

    # --- Swing metrics (from alpaca_order_events) ---
    swing_metrics: dict[str, Any] = {}

    # Build WHERE clause for order events
    order_clauses: list[str] = []
    order_params: list[Any] = []
    if start:
        order_clauses.append("date_ny >= ?")
        order_params.append(start)
    if end:
        order_clauses.append("date_ny <= ?")
        order_params.append(end)
    if strategy_id:
        order_clauses.append("strategy_id = ?")
        order_params.append(strategy_id)
    if book_id:
        order_clauses.append("book_id = ?")
        order_params.append(book_id)
    order_where = (" WHERE " + " AND ".join(order_clauses)) if order_clauses else ""

    # Get distinct strategy_ids from order events
    swing_strategy_rows = _rows(
        conn,
        f"""
        SELECT DISTINCT strategy_id
        FROM alpaca_order_events
        {order_where}
        ORDER BY strategy_id
        """,
        order_params,
    )

    for row in swing_strategy_rows:
        sid = row["strategy_id"]
        if not sid:
            continue

        # Get filled buys and sells for this strategy
        sid_clauses = list(order_clauses) + ["strategy_id = ?"]
        sid_params = list(order_params) + [sid]
        sid_where = " WHERE " + " AND ".join(sid_clauses)

        fills = _rows(
            conn,
            f"""
            SELECT symbol, side, filled_qty, filled_avg_price, filled_at,
                   stop_loss, date_ny, status
            FROM alpaca_order_events
            {sid_where}
              AND filled_qty > 0
              AND status IN ('filled', 'FILLED', 'partially_filled', 'PARTIALLY_FILLED')
            ORDER BY filled_at ASC NULLS LAST, date_ny ASC
            """,
            sid_params,
        )

        # Count total buy orders and filled buy orders for fill rate
        total_buy_rows = _rows(
            conn,
            f"""
            SELECT
                COUNT(*) AS total_buys,
                SUM(CASE WHEN filled_qty > 0 AND status IN ('filled', 'FILLED', 'partially_filled', 'PARTIALLY_FILLED') THEN 1 ELSE 0 END) AS filled_buys
            FROM alpaca_order_events
            {sid_where}
              AND side IN ('buy', 'BUY')
            """,
            sid_params,
        )
        total_buys = total_buy_rows[0]["total_buys"] if total_buy_rows else 0
        filled_buys = total_buy_rows[0]["filled_buys"] if total_buy_rows else 0

        # Pair entries (buy fills) with exits (sell fills) by symbol + time ordering
        buys_by_symbol: dict[str, list[dict]] = {}
        sells_by_symbol: dict[str, list[dict]] = {}
        for f in fills:
            side = (f.get("side") or "").lower()
            sym = f.get("symbol") or ""
            if side == "buy":
                buys_by_symbol.setdefault(sym, []).append(f)
            elif side == "sell":
                sells_by_symbol.setdefault(sym, []).append(f)

        closed_trades: list[dict] = []
        open_count = 0
        for sym, buy_list in buys_by_symbol.items():
            sell_list = sells_by_symbol.get(sym, [])
            sell_idx = 0
            for buy in buy_list:
                if sell_idx < len(sell_list):
                    sell = sell_list[sell_idx]
                    sell_idx += 1
                    entry_price = buy.get("filled_avg_price") or 0
                    exit_price = sell.get("filled_avg_price") or 0
                    stop = buy.get("stop_loss")
                    pnl = exit_price - entry_price
                    r_multiple = None
                    if stop is not None and entry_price and entry_price != stop:
                        risk = abs(entry_price - float(stop))
                        if risk > 0:
                            r_multiple = pnl / risk
                    # Holding days
                    holding_days = None
                    if buy.get("date_ny") and sell.get("date_ny"):
                        try:
                            from datetime import date as _date
                            bd = _date.fromisoformat(buy["date_ny"])
                            sd = _date.fromisoformat(sell["date_ny"])
                            holding_days = (sd - bd).days
                        except (ValueError, TypeError):
                            pass
                    closed_trades.append({
                        "symbol": sym,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "r_multiple": r_multiple,
                        "holding_days": holding_days,
                    })
                else:
                    open_count += 1

        closed_count = len(closed_trades)
        data_sufficient = closed_count >= 5

        wins = [t for t in closed_trades if t["pnl"] > 0]
        losses = [t for t in closed_trades if t["pnl"] <= 0]
        win_rate = len(wins) / closed_count if closed_count > 0 else None

        r_multiples = [t["r_multiple"] for t in closed_trades if t["r_multiple"] is not None]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else None

        gross_wins = sum(t["pnl"] for t in wins) if wins else 0
        gross_losses = abs(sum(t["pnl"] for t in losses)) if losses else 0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else None
        gross_pnl = sum(t["pnl"] for t in closed_trades)

        expectancy = None
        if win_rate is not None and closed_count > 0:
            avg_win = gross_wins / len(wins) if wins else 0
            avg_loss = gross_losses / len(losses) if losses else 0
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        holding_days_vals = [t["holding_days"] for t in closed_trades if t["holding_days"] is not None]
        avg_holding_days = sum(holding_days_vals) / len(holding_days_vals) if holding_days_vals else None

        fill_rate = filled_buys / total_buys if total_buys > 0 else None

        # Max consecutive losers
        max_consec_losers = 0
        current_streak = 0
        for t in closed_trades:
            if t["pnl"] <= 0:
                current_streak += 1
                max_consec_losers = max(max_consec_losers, current_streak)
            else:
                current_streak = 0

        swing_metrics[sid] = {
            "closed_trade_count": closed_count,
            "open_trade_count": open_count,
            "win_rate": win_rate,
            "avg_r_multiple": avg_r,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "fill_rate": fill_rate,
            "avg_holding_days": avg_holding_days,
            "max_consecutive_losers": max_consec_losers if closed_count > 0 else None,
            "gross_pnl": gross_pnl,
            "data_sufficient": data_sufficient,
        }

    # --- Portfolio metrics (from portfolio_snapshots + benchmark_prices) ---
    snap_clauses: list[str] = []
    snap_params: list[Any] = []
    if start:
        snap_clauses.append("date_ny >= ?")
        snap_params.append(start)
    if end:
        snap_clauses.append("date_ny <= ?")
        snap_params.append(end)
    snap_where = (" WHERE " + " AND ".join(snap_clauses)) if snap_clauses else ""

    snapshots = _rows(
        conn,
        f"""
        SELECT date_ny, capital_total
        FROM portfolio_snapshots
        {snap_where}
        ORDER BY date_ny ASC
        """,
        snap_params,
    )

    portfolio_metrics: dict[str, Any] = {
        "total_return": None,
        "annualized_return": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "max_drawdown": None,
        "calmar_ratio": None,
        "data_points": len(snapshots),
        "equity_curve": snapshots,
        "benchmark": "SPY",
        "benchmark_return": None,
        "excess_return": None,
        "benchmark_curve": [],
        "data_sufficient": len(snapshots) >= 10,
    }

    if len(snapshots) >= 2:
        capitals = [s["capital_total"] for s in snapshots if s.get("capital_total")]
        if len(capitals) >= 2:
            total_return = (capitals[-1] - capitals[0]) / capitals[0] if capitals[0] else None
            portfolio_metrics["total_return"] = total_return

            # Daily returns
            daily_returns: list[float] = []
            for i in range(1, len(capitals)):
                if capitals[i - 1] and capitals[i - 1] > 0:
                    daily_returns.append((capitals[i] - capitals[i - 1]) / capitals[i - 1])

            if daily_returns:
                n_days = len(daily_returns)
                avg_daily = sum(daily_returns) / n_days
                variance = sum((r - avg_daily) ** 2 for r in daily_returns) / n_days if n_days > 1 else 0
                std_daily = math.sqrt(variance) if variance > 0 else 0

                # Annualized return
                if total_return is not None and n_days > 0:
                    years = n_days / 252
                    if years > 0 and (1 + total_return) > 0:
                        portfolio_metrics["annualized_return"] = (1 + total_return) ** (1 / years) - 1

                # Sharpe (assuming 0 risk-free rate)
                if std_daily > 0:
                    portfolio_metrics["sharpe_ratio"] = round(avg_daily / std_daily * math.sqrt(252), 4)

                # Sortino
                downside_returns = [r for r in daily_returns if r < 0]
                if downside_returns:
                    downside_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
                    downside_std = math.sqrt(downside_var) if downside_var > 0 else 0
                    if downside_std > 0:
                        portfolio_metrics["sortino_ratio"] = round(avg_daily / downside_std * math.sqrt(252), 4)

                # Max drawdown
                running_max = capitals[0]
                max_dd = 0.0
                for c in capitals:
                    if c > running_max:
                        running_max = c
                    dd = (c - running_max) / running_max if running_max > 0 else 0
                    if dd < max_dd:
                        max_dd = dd
                portfolio_metrics["max_drawdown"] = round(max_dd, 6)

                # Calmar
                ann_ret = portfolio_metrics.get("annualized_return")
                if ann_ret is not None and max_dd < 0:
                    portfolio_metrics["calmar_ratio"] = round(ann_ret / abs(max_dd), 4)

    # Benchmark data
    bench_clauses: list[str] = ["symbol = 'SPY'"]
    bench_params: list[Any] = []
    if start:
        bench_clauses.append("date_ny >= ?")
        bench_params.append(start)
    if end:
        bench_clauses.append("date_ny <= ?")
        bench_params.append(end)
    bench_where = " WHERE " + " AND ".join(bench_clauses)

    bench_rows = _rows(
        conn,
        f"""
        SELECT date_ny, close
        FROM benchmark_prices
        {bench_where}
        ORDER BY date_ny ASC
        """,
        bench_params,
    )
    portfolio_metrics["benchmark_curve"] = bench_rows

    if len(bench_rows) >= 2:
        first_close = bench_rows[0]["close"]
        last_close = bench_rows[-1]["close"]
        if first_close and first_close > 0:
            bench_return = (last_close - first_close) / first_close
            portfolio_metrics["benchmark_return"] = bench_return
            if portfolio_metrics["total_return"] is not None:
                portfolio_metrics["excess_return"] = portfolio_metrics["total_return"] - bench_return

    # --- RAEC metrics (from raec_rebalance_events + raec_intents) ---
    raec_metrics: dict[str, Any] = {}
    raec_where_parts: list[str] = []
    raec_params: list[Any] = []
    if start:
        raec_where_parts.append("ny_date >= ?")
        raec_params.append(start)
    if end:
        raec_where_parts.append("ny_date <= ?")
        raec_params.append(end)
    if strategy_id:
        raec_where_parts.append("strategy_id = ?")
        raec_params.append(strategy_id)
    if book_id:
        raec_where_parts.append("book_id = ?")
        raec_params.append(book_id)
    raec_where = (" WHERE " + " AND ".join(raec_where_parts)) if raec_where_parts else ""

    raec_strat_rows = _rows(
        conn,
        f"""
        SELECT
            strategy_id,
            COALESCE(SUM(CASE WHEN should_rebalance THEN 1 ELSE 0 END), 0) AS rebalance_count,
            COUNT(DISTINCT regime) AS regime_changes,
            LAST(regime ORDER BY ny_date, ts_utc) AS current_regime
        FROM raec_rebalance_events
        {raec_where}
        GROUP BY strategy_id
        ORDER BY strategy_id
        """,
        raec_params,
    )

    for r in raec_strat_rows:
        sid = r["strategy_id"]
        # Avg turnover: average absolute delta_pct across intents for this strategy
        turnover_clauses = list(raec_where_parts)
        turnover_params = list(raec_params)
        # Replace strategy_id clause if already present
        intent_where_parts: list[str] = []
        intent_params: list[Any] = []
        if start:
            intent_where_parts.append("ny_date >= ?")
            intent_params.append(start)
        if end:
            intent_where_parts.append("ny_date <= ?")
            intent_params.append(end)
        intent_where_parts.append("strategy_id = ?")
        intent_params.append(sid)
        intent_where = " WHERE " + " AND ".join(intent_where_parts)

        turnover_rows = _rows(
            conn,
            f"""
            SELECT AVG(ABS(delta_pct)) AS avg_turnover
            FROM raec_intents
            {intent_where}
            """,
            intent_params,
        )
        avg_turnover = turnover_rows[0]["avg_turnover"] if turnover_rows and turnover_rows[0]["avg_turnover"] is not None else None

        raec_metrics[sid] = {
            "rebalance_count": r["rebalance_count"],
            "avg_turnover_pct": round(avg_turnover, 2) if avg_turnover is not None else None,
            "regime_changes": r["regime_changes"],
            "current_regime": r["current_regime"],
            "data_sufficient": r["rebalance_count"] >= 1,
        }

    # --- Order log (recent alpaca_order_events) ---
    order_log = _rows(
        conn,
        f"""
        SELECT date_ny, ts_utc, book_id, strategy_id, symbol, qty, side,
               ref_price, filled_qty, filled_avg_price, status, order_type,
               stop_loss, take_profit, alpaca_order_id
        FROM alpaca_order_events
        {order_where}
        ORDER BY date_ny DESC, ts_utc DESC NULLS LAST
        LIMIT 200
        """,
        order_params,
    )

    return {
        "swing_metrics": swing_metrics,
        "portfolio_metrics": portfolio_metrics,
        "raec_metrics": raec_metrics,
        "order_log": order_log,
    }


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
    "schwab_account_snapshots": ("schwab_account_snapshots", "ny_date"),
    "schwab_positions": ("schwab_positions", "ny_date"),
    "schwab_orders": ("schwab_orders", "ny_date"),
    "schwab_reconciliation": ("schwab_reconciliation", "ny_date"),
    "scan_candidates": ("scan_candidates", "scan_date"),
    "alpaca_order_events": ("alpaca_order_events", "date_ny"),
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

def _raec_where(
    start: str | None, end: str | None, strategy_id: str | None, book_id: str | None = None,
) -> tuple[str, list[Any]]:
    """Build WHERE clause for RAEC queries with optional date range + strategy + book filter."""
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
    if book_id:
        clauses.append("book_id = ?")
        params.append(book_id)
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def get_raec_dashboard(
    conn, start: str | None, end: str | None,
    strategy_id: str | None = None, book_id: str | None = None,
) -> dict[str, Any]:
    where, params = _raec_where(start, end, strategy_id, book_id)

    by_strategy = _rows(
        conn,
        f"""
        SELECT
            strategy_id,
            LAST(book_id ORDER BY ny_date, ts_utc) AS book_id,
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

    events = _rows(
        conn,
        f"""
        SELECT ny_date, ts_utc, strategy_id, book_id, regime,
               should_rebalance, rebalance_trigger, intent_count,
               portfolio_vol_target, portfolio_vol_realized, posted
        FROM raec_rebalance_events
        {where}
        ORDER BY ny_date DESC, ts_utc DESC
        LIMIT 200
        """,
        params,
    )

    return {
        "total_events": total_events,
        "total_rebalances": total_rebalances,
        "by_strategy": by_strategy,
        "regime_history": regime_history,
        "allocation_snapshots": allocation_snapshots,
        "events": events,
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
    strategy_id_in: set[str] | None = None,
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
    if strategy_id_in:
        placeholders = ", ".join("?" for _ in strategy_id_in)
        clauses.append(f"j.strategy_id IN ({placeholders})")
        params.extend(sorted(strategy_id_in))
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
                re.posted,
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
                NULL AS posted,
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

_STRATEGY_BOOK_MAP = {
    "RAEC_401K_V1": "ALPACA_PAPER",
    "RAEC_401K_V2": "ALPACA_PAPER",
    "RAEC_401K_V3": "SCHWAB_401K_MANUAL",
    "RAEC_401K_V4": "SCHWAB_401K_MANUAL",
    "RAEC_401K_V5": "SCHWAB_401K_MANUAL",
    "RAEC_401K_COORD": "SCHWAB_401K_MANUAL",
}


def get_raec_readiness(conn, repo_root: Path) -> dict[str, Any]:
    from datetime import date

    today = date.today().isoformat()
    strategies: list[dict[str, Any]] = []

    # Latest portfolio snapshot date (for Alpaca staleness check)
    snap_rows = _rows(conn, "SELECT MAX(date_ny) AS latest FROM portfolio_snapshots")
    latest_snapshot_date = snap_rows[0]["latest"] if snap_rows and snap_rows[0]["latest"] else None

    for sid, book_id in _STRATEGY_BOOK_MAP.items():
        state_file = repo_root / "state" / "strategies" / book_id / f"{sid}.json"
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

        # Alpaca-specific portfolio snapshot staleness
        if book_id == "ALPACA_PAPER":
            if latest_snapshot_date is None:
                warnings.append("no_portfolio_snapshot")
            elif latest_snapshot_date < today:
                warnings.append("stale_portfolio_snapshot")

        # Count ledger files for today
        ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / sid
        today_ledger_count = 0
        if ledger_dir.exists():
            today_ledger_count = sum(
                1 for f in ledger_dir.iterdir()
                if f.name.startswith(today) and f.suffix == ".jsonl"
            )

        allocs = last_allocs or {}
        strategies.append({
            "strategy_id": sid,
            "book_id": book_id,
            "state_file_exists": state_file.exists(),
            "last_eval_date": last_eval,
            "last_regime": last_regime,
            "last_known_allocations": last_allocs,
            "has_allocations": bool(allocs),
            "allocation_count": len(allocs),
            "total_weight_pct": round(sum(float(v) for v in allocs.values()), 2),
            "today_ledger_count": today_ledger_count,
            "warnings": warnings,
        })

    coord = next((s for s in strategies if s["strategy_id"] == "RAEC_401K_COORD"), None)
    return {
        "strategies": strategies,
        "coordinator": coord,
        "by_book": {
            "ALPACA_PAPER": [s for s in strategies if s["book_id"] == "ALPACA_PAPER"],
            "SCHWAB_401K_MANUAL": [s for s in strategies if s["book_id"] == "SCHWAB_401K_MANUAL"],
        },
    }


# ---------------------------------------------------------------------------
# RAEC P&L / Activity summary
# ---------------------------------------------------------------------------

def get_pnl(
    conn, start: str | None, end: str | None,
    strategy_id: str | None = None, book_id: str | None = None,
) -> dict[str, Any]:
    where, params = _raec_where(start, end, strategy_id, book_id)

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
    drift_where, drift_params = _raec_where(start, end, strategy_id, book_id)
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

    # RAEC book_id lookup: latest book_id per strategy from rebalance events
    raec_book_rows = _rows(
        conn,
        """
        SELECT strategy_id, LAST(book_id ORDER BY ny_date, ts_utc) AS book_id
        FROM raec_rebalance_events
        GROUP BY strategy_id
        """,
    )
    raec_book_map = {r["strategy_id"]: r["book_id"] for r in raec_book_rows}

    # Build unified strategy list
    strategies: list[dict[str, Any]] = []

    for row in decision_stats:
        sid = row["strategy_id"]
        strategies.append({
            "strategy_id": sid,
            "source": "decision",
            "book_id": "ALPACA_PAPER",
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
            "book_id": raec_book_map.get(sid, ""),
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

def get_schwab_overview(
    conn, start: str | None, end: str | None
) -> dict[str, Any]:
    # Latest account balance
    latest_account_rows = _rows(
        conn,
        """
        SELECT ny_date, as_of_utc, cash, market_value, total_value
        FROM schwab_account_snapshots
        ORDER BY ny_date DESC, as_of_utc DESC
        LIMIT 1
        """,
    )
    latest_account = latest_account_rows[0] if latest_account_rows else None

    # Balance history (filtered by date range)
    where, params = _date_clause("ny_date", start, end)
    balance_history = _rows(
        conn,
        f"""
        SELECT ny_date, cash, market_value, total_value
        FROM schwab_account_snapshots
        {where}
        ORDER BY ny_date ASC
        """,
        params,
    )

    # Positions for the latest date
    positions_date = latest_account["ny_date"] if latest_account else None
    positions: list[dict[str, Any]] = []
    if positions_date:
        positions = _rows(
            conn,
            """
            SELECT symbol, qty, cost_basis, market_value,
                   market_value / SUM(market_value) OVER () * 100 AS weight_pct
            FROM schwab_positions
            WHERE ny_date = ?
            ORDER BY market_value DESC
            """,
            [positions_date],
        )

    # Recent orders (most recent 50)
    orders = _rows(
        conn,
        """
        SELECT ny_date, order_id, symbol, side, qty, filled_qty, status, submitted_at, filled_at
        FROM schwab_orders
        ORDER BY ny_date DESC, submitted_at DESC NULLS LAST
        LIMIT 50
        """,
    )

    # Latest reconciliation
    latest_recon_rows = _rows(
        conn,
        """
        SELECT ny_date, as_of_utc, broker_position_count, drift_symbol_count, drift_intent_count,
               drift_reason_codes_json, symbols_json
        FROM schwab_reconciliation
        ORDER BY ny_date DESC, as_of_utc DESC
        LIMIT 1
        """,
    )
    latest_reconciliation = latest_recon_rows[0] if latest_recon_rows else None

    return {
        "latest_account": latest_account,
        "balance_history": balance_history,
        "positions": positions,
        "positions_date": positions_date,
        "orders": orders,
        "latest_reconciliation": latest_reconciliation,
    }


_ALPACA_STRATEGY_IDS = {"S1_AVWAP_CORE", "S2_LETF_ORB_AGGRO", "RAEC_401K_V1", "RAEC_401K_V2"}
_SCHWAB_STRATEGY_IDS = {"RAEC_401K_V3", "RAEC_401K_V4", "RAEC_401K_V5", "RAEC_401K_COORD"}


def _strategy_ids_for_book(book_id: str | None) -> set[str] | None:
    if book_id == "ALPACA_PAPER":
        return _ALPACA_STRATEGY_IDS
    if book_id == "SCHWAB_401K_MANUAL":
        return _SCHWAB_STRATEGY_IDS
    return None


def get_trade_analytics(
    conn, start: str | None, end: str | None,
    strategy_id: str | None = None, book_id: str | None = None,
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
    sid_set = _strategy_ids_for_book(book_id)
    if sid_set:
        placeholders = ", ".join("?" for _ in sid_set)
        clauses.append(f"strategy_id IN ({placeholders})")
        params.extend(sorted(sid_set))
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


# ---------------------------------------------------------------------------
# Scan Candidates
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Today's Trades (coordinator run + intents + Schwab context)
# ---------------------------------------------------------------------------

def get_todays_trades(
    conn, date: str, repo_root: "Path",
) -> dict[str, Any]:
    """Pull the coordinator run, rebalance events, trade intents, allocations,
    and Schwab positions for a given trading date."""
    from pathlib import Path as _Path

    # --- Coordinator run ---
    coordinator_runs = _rows(
        conn,
        """
        SELECT ny_date, ts_utc, capital_split_json, sub_results_json
        FROM raec_coordinator_runs
        WHERE ny_date = ?
        ORDER BY ts_utc DESC
        LIMIT 1
        """,
        [date],
    )
    coordinator = coordinator_runs[0] if coordinator_runs else None
    if coordinator:
        coordinator["capital_split"] = json.loads(coordinator.pop("capital_split_json", "{}"))
        coordinator["sub_results"] = json.loads(coordinator.pop("sub_results_json", "{}"))

    # --- Rebalance events for today ---
    events = _rows(
        conn,
        """
        SELECT ny_date, ts_utc, strategy_id, book_id, regime,
               should_rebalance, rebalance_trigger, intent_count, posted
        FROM raec_rebalance_events
        WHERE ny_date = ?
        ORDER BY ts_utc DESC
        """,
        [date],
    )

    # --- Trade intents (the actual trades to execute) ---
    intents = _rows(
        conn,
        """
        SELECT ny_date, ts_utc, strategy_id, intent_id, symbol, side,
               delta_pct, target_pct, current_pct
        FROM raec_intents
        WHERE ny_date = ?
        ORDER BY strategy_id, symbol
        """,
        [date],
    )

    # --- Target vs current allocations for today ---
    allocations = _rows(
        conn,
        """
        SELECT ny_date, strategy_id, alloc_type, symbol, weight_pct
        FROM raec_allocations
        WHERE ny_date = ?
        ORDER BY strategy_id, alloc_type, symbol
        """,
        [date],
    )

    # --- Latest Schwab account balance ---
    account_rows = _rows(
        conn,
        """
        SELECT ny_date, as_of_utc, cash, market_value, total_value
        FROM schwab_account_snapshots
        ORDER BY ny_date DESC, as_of_utc DESC
        LIMIT 1
        """,
    )
    schwab_account = account_rows[0] if account_rows else None

    # --- Latest Schwab positions ---
    positions_date = schwab_account["ny_date"] if schwab_account else None
    schwab_positions: list[dict[str, Any]] = []
    if positions_date:
        schwab_positions = _rows(
            conn,
            """
            SELECT symbol, qty, cost_basis, market_value,
                   market_value / NULLIF(SUM(market_value) OVER (), 0) * 100 AS weight_pct
            FROM schwab_positions
            WHERE ny_date = ?
            ORDER BY market_value DESC
            """,
            [positions_date],
        )

    # --- Strategy state readiness (quick check) ---
    strategies_state: list[dict[str, Any]] = []
    for sid, book_id in _STRATEGY_BOOK_MAP.items():
        state_file = _Path(repo_root) / "state" / "strategies" / book_id / f"{sid}.json"
        state_data: dict[str, Any] = {}
        if state_file.exists():
            try:
                state_data = json.loads(state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        strategies_state.append({
            "strategy_id": sid,
            "book_id": book_id,
            "last_eval_date": state_data.get("last_eval_date"),
            "last_regime": state_data.get("last_regime"),
        })

    has_trades = len(intents) > 0
    any_rebalance = any(e.get("should_rebalance") for e in events)

    return {
        "date": date,
        "has_trades": has_trades,
        "any_rebalance": any_rebalance,
        "coordinator": coordinator,
        "events": events,
        "intents": intents,
        "allocations": allocations,
        "schwab_account": schwab_account,
        "schwab_positions": schwab_positions,
        "schwab_positions_date": positions_date,
        "strategies_state": strategies_state,
    }


def get_chart_data(
    cache_dir: "Path",
    symbol: str,
    anchor: str | None = None,
    days: int = 90,
) -> dict[str, Any]:
    """Load OHLCV candles + optional AVWAP line for a symbol from the parquet cache."""
    import numpy as np

    parquet_path = Path(cache_dir) / "ohlcv_history.parquet"
    if not parquet_path.exists():
        return {"candles": [], "avwap": [], "anchor_date": None}

    df = pd.read_parquet(parquet_path)
    if "Ticker" not in df.columns:
        return {"candles": [], "avwap": [], "anchor_date": None}

    sym = symbol.upper()
    mask = df["Ticker"].astype(str).str.upper() == sym
    sub = df.loc[mask].copy()
    if sub.empty:
        return {"candles": [], "avwap": [], "anchor_date": None}

    sub["Date"] = pd.to_datetime(sub["Date"])
    sub = sub.sort_values("Date").tail(days).reset_index(drop=True)

    candles = []
    for _, row in sub.iterrows():
        candles.append({
            "time": row["Date"].strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        })

    # Compute AVWAP if anchor date provided
    avwap_points: list[dict[str, Any]] = []
    anchor_date_out: str | None = None
    if anchor and len(sub) > 1:
        try:
            anchor_dt = pd.Timestamp(anchor)
            anchor_date_out = anchor_dt.strftime("%Y-%m-%d")
            # Find the anchor location in the dataframe
            anchor_mask = sub["Date"] >= anchor_dt
            if anchor_mask.any():
                anchor_loc = int(anchor_mask.idxmax())
                # Compute AVWAP inline (same formula as anchors.py)
                tp = (sub["High"] + sub["Low"] + sub["Close"]) / 3.0
                vol = sub["Volume"].astype(float)
                avwap = pd.Series(index=sub.index, dtype=float)
                avwap.iloc[:anchor_loc] = np.nan
                tp2 = tp.iloc[anchor_loc:]
                v2 = vol.iloc[anchor_loc:]
                cumvol = v2.cumsum()
                cumvol = cumvol.replace(0, np.nan)
                avwap.iloc[anchor_loc:] = (tp2 * v2).cumsum() / cumvol

                for i, val in avwap.items():
                    if pd.notna(val):
                        avwap_points.append({
                            "time": sub.loc[i, "Date"].strftime("%Y-%m-%d"),
                            "value": round(float(val), 4),
                        })
        except (ValueError, KeyError):
            pass

    return {"candles": candles, "avwap": avwap_points, "anchor_date": anchor_date_out}


def get_scan_candidates(
    conn,
    *,
    date: str | None = None,
    symbol: str | None = None,
    direction: str | None = None,
    sector: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if date:
        clauses.append("scan_date = ?")
        params.append(date)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if direction:
        clauses.append("LOWER(direction) = ?")
        params.append(direction.lower())
    if sector:
        clauses.append("sector = ?")
        params.append(sector)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    safe_limit = max(1, min(limit, 5000))

    rows = _rows(
        conn,
        f"""
        SELECT scan_date, symbol, direction, trend_tier, price,
               entry_level, entry_dist_pct, stop_loss, target_r1, target_r2,
               trend_score, sector, anchor, anchor_date, avwap_slope, avwap_confluence, sector_rs,
               setup_vwap_control, setup_vwap_reclaim, setup_vwap_acceptance, setup_vwap_dist_pct,
               setup_avwap_control, setup_avwap_reclaim, setup_avwap_acceptance, setup_avwap_dist_pct,
               setup_extension_state, setup_gap_reset, setup_structure_state
        FROM scan_candidates
        {where}
        ORDER BY trend_score DESC NULLS LAST
        LIMIT ?
        """,
        params + [safe_limit],
    )

    latest_date_rows = _rows(conn, "SELECT MAX(scan_date) AS latest FROM scan_candidates")
    latest_date = latest_date_rows[0]["latest"] if latest_date_rows and latest_date_rows[0]["latest"] else None

    return {
        "count": len(rows),
        "latest_date": latest_date,
        "rows": rows,
    }
