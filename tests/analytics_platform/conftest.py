from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from analytics_platform.backend.config import Settings


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "ledger" / "PORTFOLIO_DECISIONS").mkdir(parents=True)
    (tmp_path / "ledger" / "STRATEGY_SIGNALS" / "S2_LETF_ORB_AGGRO").mkdir(parents=True)
    (tmp_path / "ledger" / "PORTFOLIO_RISK_CONTROLS").mkdir(parents=True)
    (tmp_path / "ledger" / "PORTFOLIO_THROTTLE").mkdir(parents=True)
    (tmp_path / "ledger" / "REGIME_E1").mkdir(parents=True)
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "backtests" / "suite_a" / "baseline").mkdir(parents=True)

    decision_record = {
        "schema_version": "1.0",
        "decision_id": "dec-001",
        "ts_utc": "2026-02-10T14:35:00+00:00",
        "ny_date": "2026-02-10",
        "mode": {"execution_mode": "SCHWAB_401K_MANUAL", "dry_run_forced": True},
        "gates": {
            "live_gate_applied": True,
            "market": {"is_open": True},
            "blocks": [{"code": "entry_delay_after_open", "message": "delay active"}],
        },
        "intents": {
            "intent_count": 2,
            "intents": [
                {"strategy_id": "S1_AVWAP_CORE", "symbol": "AAPL", "qty": 4, "side": "buy"},
                {"strategy_id": "S2_LETF_ORB_AGGRO", "symbol": "GOOGL", "qty": 3, "side": "buy"},
            ],
        },
        "intents_meta": {
            "entry_intents_created_count": 2,
            "entry_rejections": {
                "accepted": 2,
                "rejected": 1,
                "candidates_seen": 3,
                "reason_counts": {"boh_not_confirmed": 1},
                "rejected_symbols": [{"symbol": "MSFT", "reason": "boh_not_confirmed"}],
            }
        },
        "build": {"git_sha": "abc123"},
    }
    (tmp_path / "ledger" / "PORTFOLIO_DECISIONS" / "2026-02-10.jsonl").write_text(
        json.dumps(decision_record) + "\n", encoding="utf-8"
    )

    signal_record = {
        "record_type": "STRATEGY_SIGNAL",
        "strategy_id": "S2_LETF_ORB_AGGRO",
        "book_id": "SCHWAB_401K_MANUAL",
        "asof_date": "2026-02-10",
        "run_id": "run-001",
        "symbol": "GOOGL",
        "complex": "internet_platform",
        "eligible": True,
        "selected": True,
        "score": 0.22,
        "reason_codes": [],
        "gates": {"trend_ok": True},
        "metrics": {"ret_short": 0.12},
        "candidate": {"Symbol": "GOOGL"},
    }
    (tmp_path / "ledger" / "STRATEGY_SIGNALS" / "S2_LETF_ORB_AGGRO" / "2026-02-10.jsonl").write_text(
        json.dumps(signal_record) + "\n", encoding="utf-8"
    )

    risk_record = {
        "record_type": "PORTFOLIO_RISK_CONTROLS",
        "as_of_utc": "2026-02-10T14:35:00+00:00",
        "requested_ny_date": "2026-02-10",
        "resolved_ny_date": "2026-02-10",
        "risk_controls": {
            "risk_multiplier": 0.8,
            "max_positions": 5,
            "max_gross_exposure": 5000,
            "per_position_cap": 0.2,
            "throttle_reason": "risk_multiplier",
        },
    }
    (tmp_path / "ledger" / "PORTFOLIO_RISK_CONTROLS" / "2026-02-10.jsonl").write_text(
        json.dumps(risk_record) + "\n", encoding="utf-8"
    )

    throttle_record = {
        "record_type": "PORTFOLIO_THROTTLE",
        "as_of_utc": "2026-02-10T14:30:00+00:00",
        "requested_ny_date": "2026-02-10",
        "resolved_ny_date": "2026-02-10",
        "regime_id": "RISK_ON",
        "throttle": {"risk_multiplier": 1.0, "max_new_positions_multiplier": 1.0, "reasons": []},
    }
    (tmp_path / "ledger" / "PORTFOLIO_THROTTLE" / "2026-02-10.jsonl").write_text(
        json.dumps(throttle_record) + "\n", encoding="utf-8"
    )

    regime_record = {
        "record_type": "REGIME_E1",
        "as_of_utc": "2026-02-10T14:25:00+00:00",
        "requested_ny_date": "2026-02-10",
        "resolved_ny_date": "2026-02-10",
        "regime_id": "RISK_ON",
        "reason_codes": ["momentum"],
        "inputs_snapshot": {"spy": 0.2},
    }
    (tmp_path / "ledger" / "REGIME_E1" / "2026-02-10.jsonl").write_text(
        json.dumps(regime_record) + "\n", encoding="utf-8"
    )

    (tmp_path / "state" / "portfolio_decision_latest.json").write_text(
        json.dumps(decision_record), encoding="utf-8"
    )

    (tmp_path / "backtests" / "suite_a" / "baseline" / "summary.json").write_text(
        json.dumps({"cagr": 0.12, "max_drawdown": -0.08}), encoding="utf-8"
    )
    (tmp_path / "backtests" / "suite_a" / "baseline" / "equity_curve.csv").write_text(
        "date,equity\n2026-01-01,100000\n2026-01-02,100500\n",
        encoding="utf-8",
    )
    (tmp_path / "backtests" / "suite_a" / "baseline" / "trades.csv").write_text(
        "symbol,pnl\nAAPL,100\n", encoding="utf-8"
    )

    # --- RAEC state directories for readiness checks ---
    (tmp_path / "state" / "strategies" / "SCHWAB_401K_MANUAL").mkdir(parents=True)
    (tmp_path / "state" / "strategies" / "ALPACA_PAPER").mkdir(parents=True)

    # Write V1/V2 state files (Alpaca)
    v1_state = {
        "last_eval_date": "2026-02-10",
        "last_regime": "RISK_ON",
        "last_known_allocations": {"TQQQ": 40.0, "SOXL": 30.0, "BIL": 30.0},
    }
    (tmp_path / "state" / "strategies" / "ALPACA_PAPER" / "RAEC_401K_V1.json").write_text(
        json.dumps(v1_state), encoding="utf-8"
    )
    v2_state = {
        "last_eval_date": "2026-02-10",
        "last_regime": "TRANSITION",
        "last_known_allocations": {"QQQ": 50.0, "BIL": 50.0},
    }
    (tmp_path / "state" / "strategies" / "ALPACA_PAPER" / "RAEC_401K_V2.json").write_text(
        json.dumps(v2_state), encoding="utf-8"
    )

    # --- RAEC rebalance event fixture ---
    (tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_V1").mkdir(parents=True)
    (tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_V3").mkdir(parents=True)
    (tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_COORD").mkdir(parents=True)

    # V1 rebalance event (Alpaca)
    raec_v1_event = {
        "record_type": "RAEC_REBALANCE_EVENT",
        "ts_utc": "2026-02-10T14:30:00+00:00",
        "ny_date": "2026-02-10",
        "book_id": "ALPACA_PAPER",
        "strategy_id": "RAEC_401K_V1",
        "regime": "RISK_ON",
        "should_rebalance": False,
        "rebalance_trigger": "none",
        "targets": {"TQQQ": 40.0, "SOXL": 30.0, "BIL": 30.0},
        "current_allocations": {"TQQQ": 40.0, "SOXL": 30.0, "BIL": 30.0},
        "intent_count": 0,
        "intents": [],
        "signals": {},
        "portfolio_vol_target": 0.20,
        "portfolio_vol_realized": 0.18,
        "posted": False,
    }
    (tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_V1" / "2026-02-10.jsonl").write_text(
        json.dumps(raec_v1_event) + "\n", encoding="utf-8"
    )

    raec_rebalance_event = {
        "record_type": "RAEC_REBALANCE_EVENT",
        "ts_utc": "2026-02-10T15:00:00+00:00",
        "ny_date": "2026-02-10",
        "book_id": "SCHWAB_401K_MANUAL",
        "strategy_id": "RAEC_401K_V3",
        "regime": "RISK_ON",
        "should_rebalance": True,
        "rebalance_trigger": "daily",
        "targets": {"TQQQ": 35.0, "SOXL": 25.0, "BIL": 40.0},
        "current_allocations": {"SPY": 50.0, "BIL": 50.0},
        "intent_count": 3,
        "intents": [
            {"intent_id": "intent-raec-001", "symbol": "TQQQ", "side": "BUY", "delta_pct": 35.0, "target_pct": 35.0, "current_pct": 0.0},
            {"intent_id": "intent-raec-002", "symbol": "SOXL", "side": "BUY", "delta_pct": 25.0, "target_pct": 25.0, "current_pct": 0.0},
            {"intent_id": "intent-raec-003", "symbol": "SPY", "side": "SELL", "delta_pct": -50.0, "target_pct": 0.0, "current_pct": 50.0},
        ],
        "signals": {"sma200": 180.5, "sma50": 195.3, "vol20": 0.185, "anchor_symbol": "VTI"},
        "momentum_scores": [{"symbol": "TQQQ", "score": 2.45, "ret_6m": 0.152}],
        "portfolio_vol_target": 0.18,
        "portfolio_vol_realized": 0.165,
        "posted": True,
        "notice": None,
        "build_git_sha": "abc123",
    }
    (tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_V3" / "2026-02-10.jsonl").write_text(
        json.dumps(raec_rebalance_event) + "\n", encoding="utf-8"
    )

    raec_coordinator_run = {
        "record_type": "RAEC_COORDINATOR_RUN",
        "ts_utc": "2026-02-10T15:05:00+00:00",
        "ny_date": "2026-02-10",
        "book_id": "SCHWAB_401K_MANUAL",
        "strategy_id": "RAEC_401K_COORD",
        "capital_split": {"v3": 0.40, "v4": 0.30, "v5": 0.30},
        "sub_strategy_results": {
            "v3": {"regime": "RISK_ON", "should_rebalance": True, "intent_count": 3},
            "v4": {"regime": "TRANSITION", "should_rebalance": False, "intent_count": 0},
            "v5": {"regime": "RISK_ON", "should_rebalance": True, "intent_count": 1},
        },
    }
    (tmp_path / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_COORD" / "2026-02-10.jsonl").write_text(
        json.dumps(raec_coordinator_run) + "\n", encoding="utf-8"
    )

    # --- Execution slippage fixture ---
    (tmp_path / "ledger" / "EXECUTION_SLIPPAGE").mkdir(parents=True)
    slippage_records = [
        {"schema_version":1,"record_type":"EXECUTION_SLIPPAGE","date_ny":"2026-02-10","symbol":"AAPL","strategy_id":"S1_AVWAP_CORE","expected_price":185.50,"ideal_fill_price":185.45,"actual_fill_price":185.52,"slippage_bps":3.78,"adv_shares_20d":55000000.0,"liquidity_bucket":"mega","fill_ts_utc":"2026-02-10T15:30:00+00:00","time_of_day_bucket":"10:30-11:00"},
        {"schema_version":1,"record_type":"EXECUTION_SLIPPAGE","date_ny":"2026-02-10","symbol":"CRWD","strategy_id":"S1_AVWAP_CORE","expected_price":320.00,"ideal_fill_price":319.80,"actual_fill_price":320.45,"slippage_bps":20.32,"adv_shares_20d":900000.0,"liquidity_bucket":"mid","fill_ts_utc":"2026-02-10T14:45:00+00:00","time_of_day_bucket":"09:45-10:00"},
        {"schema_version":1,"record_type":"EXECUTION_SLIPPAGE","date_ny":"2026-02-10","symbol":"TQQQ","strategy_id":"S2_LETF_ORB_AGGRO","expected_price":75.00,"ideal_fill_price":74.95,"actual_fill_price":75.08,"slippage_bps":17.35,"adv_shares_20d":3500000.0,"liquidity_bucket":"large","fill_ts_utc":"2026-02-10T14:35:00+00:00","time_of_day_bucket":"09:35-10:00"},
    ]
    (tmp_path / "ledger" / "EXECUTION_SLIPPAGE" / "2026-02-10.jsonl").write_text(
        "\n".join(json.dumps(r) for r in slippage_records) + "\n", encoding="utf-8"
    )

    # --- Portfolio risk attribution fixture ---
    (tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION").mkdir(parents=True)
    risk_attribution_record = {
        "record_type": "PORTFOLIO_RISK_ATTRIBUTION",
        "schema_version": 1,
        "date_ny": "2026-02-10",
        "ts_utc": "2026-02-10T21:00:00+00:00",
        "decision_id": "risk-attr-001",
        "strategy_id": "S1_AVWAP_CORE",
        "symbol": "AAPL",
        "action": "SIZE_REDUCE",
        "reason_codes": ["regime_transition", "vol_spike"],
        "pct_delta": -15.0,
        "baseline_exposure": 50000.0,
    }
    (tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION" / "2026-02-10.jsonl").write_text(
        json.dumps(risk_attribution_record) + "\n", encoding="utf-8"
    )

    # --- Portfolio snapshot fixture ---
    (tmp_path / "analytics" / "artifacts" / "portfolio_snapshots").mkdir(parents=True, exist_ok=True)
    portfolio_snapshot = {
        "schema_version": 2,
        "date_ny": "2026-02-10",
        "run_id": "fixture-run-001",
        "strategy_ids": ["S1_AVWAP_CORE", "S2_LETF_ORB_AGGRO"],
        "capital": {"total": 100000.0, "cash": 45000.0, "invested": 55000.0},
        "gross_exposure": 55000.0,
        "net_exposure": 42000.0,
        "positions": [
            {"strategy_id": "S1_AVWAP_CORE", "symbol": "AAPL", "qty": 100, "avg_price": 180.0, "mark_price": 185.50, "notional": 18550.0},
            {"strategy_id": "S1_AVWAP_CORE", "symbol": "MSFT", "qty": 50, "avg_price": 410.0, "mark_price": 420.0, "notional": 21000.0},
            {"strategy_id": "S2_LETF_ORB_AGGRO", "symbol": "TQQQ", "qty": 200, "avg_price": 75.0, "mark_price": 77.25, "notional": 15450.0},
        ],
        "pnl": {"realized_today": 150.0, "unrealized": 2000.0, "fees_today": 2.50},
        "metrics": {},
        "provenance": {"ledger_paths": [], "input_hashes": {}},
    }
    (tmp_path / "analytics" / "artifacts" / "portfolio_snapshots" / "2026-02-10.json").write_text(
        json.dumps(portfolio_snapshot, indent=2) + "\n", encoding="utf-8"
    )

    # --- Schwab readonly ledger fixtures ---
    (tmp_path / "ledger" / "SCHWAB_401K_MANUAL").mkdir(parents=True)

    schwab_account_snapshot = {
        "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
        "snapshot_id": "snap-acct-001",
        "ny_date": "2026-02-10",
        "schema_version": 1,
        "book_id": "SCHWAB_401K_MANUAL",
        "as_of_utc": "2026-02-10T16:00:00+00:00",
        "cash": "5000.0000",
        "market_value": "20922.8300",
        "total_value": "25922.8300",
        "provenance": {"module": "analytics.schwab_readonly_storage"},
    }
    schwab_positions_snapshot = {
        "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
        "snapshot_id": "snap-pos-001",
        "ny_date": "2026-02-10",
        "schema_version": 1,
        "book_id": "SCHWAB_401K_MANUAL",
        "as_of_utc": "2026-02-10T16:00:00+00:00",
        "positions": [
            {"symbol": "TQQQ", "qty": "100.000000", "cost_basis": "6500.0000", "market_value": "7725.0000"},
            {"symbol": "SOXL", "qty": "50.000000", "cost_basis": "5000.0000", "market_value": "5200.0000"},
            {"symbol": "BIL", "qty": "200.000000", "cost_basis": "8000.0000", "market_value": "7997.8300"},
        ],
        "provenance": {"module": "analytics.schwab_readonly_storage"},
    }
    schwab_orders_snapshot = {
        "record_type": "SCHWAB_READONLY_ORDERS_SNAPSHOT",
        "snapshot_id": "snap-ord-001",
        "ny_date": "2026-02-10",
        "schema_version": 1,
        "book_id": "SCHWAB_401K_MANUAL",
        "as_of_utc": "2026-02-10T16:00:00+00:00",
        "orders": [
            {
                "order_id": "order-001",
                "symbol": "TQQQ",
                "side": "BUY",
                "qty": "50.000000",
                "filled_qty": "50.000000",
                "status": "FILLED",
                "submitted_at": "2026-02-10T14:30:00+00:00",
                "filled_at": "2026-02-10T14:30:05+00:00",
            },
        ],
        "provenance": {"module": "analytics.schwab_readonly_storage"},
    }
    schwab_reconciliation = {
        "record_type": "SCHWAB_READONLY_RECONCILIATION",
        "reconciliation_id": "recon-001",
        "ny_date": "2026-02-10",
        "book_id": "SCHWAB_401K_MANUAL",
        "as_of_utc": "2026-02-10T16:05:00+00:00",
        "report": {
            "schema_version": 1,
            "book_id": "SCHWAB_401K_MANUAL",
            "ny_date": "2026-02-10",
            "as_of_utc": "2026-02-10T16:05:00+00:00",
            "counts": {
                "intent_count": 3,
                "confirmation_count": 3,
                "broker_position_count": 3,
                "drift_intent_count": 0,
                "drift_symbol_count": 0,
                "unknown_confirmation_count": 0,
            },
            "drift_reason_codes": [],
            "symbols": [
                {"symbol": "TQQQ", "intent_qty_total": "100.000000", "broker_qty": "100.000000", "drift_reason_codes": []},
                {"symbol": "SOXL", "intent_qty_total": "50.000000", "broker_qty": "50.000000", "drift_reason_codes": []},
                {"symbol": "BIL", "intent_qty_total": "200.000000", "broker_qty": "200.000000", "drift_reason_codes": []},
            ],
        },
        "provenance": {"module": "analytics.schwab_readonly_reconciliation"},
    }
    schwab_lines = "\n".join(
        json.dumps(r)
        for r in [schwab_account_snapshot, schwab_positions_snapshot, schwab_orders_snapshot, schwab_reconciliation]
    ) + "\n"
    (tmp_path / "ledger" / "SCHWAB_401K_MANUAL" / "2026-02-10.jsonl").write_text(schwab_lines, encoding="utf-8")

    # Second Schwab snapshot day for performance chart (need 2+ data points)
    schwab_account_snapshot_d2 = {
        "record_type": "SCHWAB_READONLY_ACCOUNT_SNAPSHOT",
        "snapshot_id": "snap-acct-002",
        "ny_date": "2026-02-11",
        "schema_version": 1,
        "book_id": "SCHWAB_401K_MANUAL",
        "as_of_utc": "2026-02-11T16:00:00+00:00",
        "cash": "5000.0000",
        "market_value": "21500.0000",
        "total_value": "26500.0000",
        "provenance": {"module": "analytics.schwab_readonly_storage"},
    }
    schwab_positions_snapshot_d2 = {
        "record_type": "SCHWAB_READONLY_POSITIONS_SNAPSHOT",
        "snapshot_id": "snap-pos-002",
        "ny_date": "2026-02-11",
        "schema_version": 1,
        "book_id": "SCHWAB_401K_MANUAL",
        "as_of_utc": "2026-02-11T16:00:00+00:00",
        "positions": [
            {"symbol": "TQQQ", "qty": "100.000000", "cost_basis": "6500.0000", "market_value": "8000.0000"},
            {"symbol": "SOXL", "qty": "50.000000", "cost_basis": "5000.0000", "market_value": "5400.0000"},
            {"symbol": "BIL", "qty": "200.000000", "cost_basis": "8000.0000", "market_value": "8100.0000"},
        ],
        "provenance": {"module": "analytics.schwab_readonly_storage"},
    }
    schwab_d2_lines = "\n".join(
        json.dumps(r) for r in [schwab_account_snapshot_d2, schwab_positions_snapshot_d2]
    ) + "\n"
    (tmp_path / "ledger" / "SCHWAB_401K_MANUAL" / "2026-02-11.jsonl").write_text(
        schwab_d2_lines, encoding="utf-8"
    )

    # --- Benchmark prices parquet (SPY + VTI) ---
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    bench_df = pd.DataFrame([
        {"Symbol": "SPY", "Date": "2026-02-10", "Close": 500.0},
        {"Symbol": "SPY", "Date": "2026-02-11", "Close": 505.0},
        {"Symbol": "VTI", "Date": "2026-02-10", "Close": 250.0},
        {"Symbol": "VTI", "Date": "2026-02-11", "Close": 253.0},
    ])
    bench_df.to_parquet(tmp_path / "cache" / "ohlcv_history.parquet", index=False)

    # --- Alpaca order event fixtures ---
    (tmp_path / "ledger" / "ALPACA_PAPER").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledger" / "S2_ALPACA").mkdir(parents=True, exist_ok=True)

    alpaca_paper_orders = [
        {
            "event_type": "ORDER_STATUS",
            "date_ny": "2026-02-10",
            "ts_utc": "2026-02-10T14:35:00+00:00",
            "book_id": "ALPACA_PAPER",
            "strategy_id": "RAEC_401K_V2",
            "intent_id": "intent-alp-001",
            "alpaca_order_id": "alp-order-001",
            "symbol": "QQQ",
            "qty": 10,
            "side": "buy",
            "ref_price": 450.0,
            "notional": 4500.0,
            "status": "filled",
            "filled_qty": 10,
            "filled_avg_price": 450.50,
            "filled_at": "2026-02-10T14:35:05+00:00",
            "created_at": "2026-02-10T14:35:00+00:00",
            "updated_at": "2026-02-10T14:35:05+00:00",
            "order_type": "market",
            "stop_loss": 440.0,
            "take_profit": 470.0,
        },
    ]
    (tmp_path / "ledger" / "ALPACA_PAPER" / "2026-02-10.jsonl").write_text(
        "\n".join(json.dumps(r) for r in alpaca_paper_orders) + "\n", encoding="utf-8"
    )

    s2_alpaca_orders = [
        {
            "event_type": "ORDER_STATUS",
            "date_ny": "2026-02-10",
            "ts_utc": "2026-02-10T14:36:00+00:00",
            "book_id": "S2_ALPACA",
            "strategy_id": "S2_LETF_ORB_AGGRO",
            "intent_id": "intent-s2-001",
            "alpaca_order_id": "s2-order-001",
            "symbol": "TQQQ",
            "qty": 50,
            "side": "buy",
            "ref_price": 75.0,
            "notional": 3750.0,
            "status": "filled",
            "filled_qty": 50,
            "filled_avg_price": 75.10,
            "filled_at": "2026-02-10T14:36:05+00:00",
            "created_at": "2026-02-10T14:36:00+00:00",
            "updated_at": "2026-02-10T14:36:05+00:00",
            "order_type": "market",
            "stop_loss": 73.0,
            "take_profit": 80.0,
        },
        {
            "event_type": "ORDER_STATUS",
            "date_ny": "2026-02-10",
            "ts_utc": "2026-02-10T15:30:00+00:00",
            "book_id": "S2_ALPACA",
            "strategy_id": "S2_LETF_ORB_AGGRO",
            "intent_id": "intent-s2-002",
            "alpaca_order_id": "s2-order-002",
            "symbol": "TQQQ",
            "qty": 50,
            "side": "sell",
            "ref_price": 77.0,
            "notional": 3850.0,
            "status": "filled",
            "filled_qty": 50,
            "filled_avg_price": 77.25,
            "filled_at": "2026-02-10T15:30:05+00:00",
            "created_at": "2026-02-10T15:30:00+00:00",
            "updated_at": "2026-02-10T15:30:05+00:00",
            "order_type": "market",
            "stop_loss": None,
            "take_profit": None,
        },
    ]
    (tmp_path / "ledger" / "S2_ALPACA" / "2026-02-10.jsonl").write_text(
        "\n".join(json.dumps(r) for r in s2_alpaca_orders) + "\n", encoding="utf-8"
    )

    # --- Scan candidates CSV fixture ---
    scan_csv = (
        "SchemaVersion,ScanDate,Symbol,Direction,TrendTier,Price,Entry_Level,Entry_DistPct,"
        "Stop_Loss,Target_R1,Target_R2,TrendScore,Sector,Anchor,AVWAP_Slope,AVWAP_Confluence,Sector_RS,"
        "Setup_VWAP_Control,Setup_VWAP_Reclaim,Setup_VWAP_Acceptance,Setup_VWAP_DistPct,"
        "Setup_AVWAP_Control,Setup_AVWAP_Reclaim,Setup_AVWAP_Acceptance,Setup_AVWAP_DistPct,"
        "Setup_Extension_State,Setup_Gap_Reset,Setup_Structure_State\n"
        "1,2026-02-10,AAPL,Long,A,185.50,183.00,1.36,181.00,188.00,190.00,42.5,"
        "Technology,SwingLow20,0.0120,3,1.0350,bullish,none,bullish,1.36,"
        "bullish,none,bullish,1.36,moderate,none,bullish\n"
        "1,2026-02-10,TSLA,Short,B,220.00,225.00,2.27,228.00,215.00,210.00,35.2,"
        "Consumer Discretionary,SwingHigh20,-0.0080,1,0.9800,bearish,none,bearish,2.27,"
        "bearish,none,bearish,2.27,moderate,none,bearish\n"
    )
    (tmp_path / "daily_candidates.csv").write_text(scan_csv, encoding="utf-8")

    return tmp_path


@pytest.fixture()
def analytics_settings(sample_repo: Path) -> Settings:
    data_dir = sample_repo / "analytics_platform" / "data"
    return Settings(
        repo_root=sample_repo,
        data_dir=data_dir,
        db_path=data_dir / "analytics.duckdb",
        refresh_seconds=60,
        enable_scheduler=False,
    )
