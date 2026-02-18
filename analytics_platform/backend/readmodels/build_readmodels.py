from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from analytics_platform.backend.config import Settings
from analytics_platform.backend.db import connect_rw
from analytics_platform.backend.models import BuildResult, utc_now_iso


DEFAULT_STRATEGY_ID = "S1_AVWAP_CORE"
S2_STRATEGY_ID = "S2_LETF_ORB_AGGRO"


@dataclass
class SourceHealth:
    source_name: str
    source_glob: str
    file_count: int = 0
    row_count: int = 0
    latest_mtime_utc: str | None = None
    parse_status: str = "ok"
    last_error: str | None = None


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _flatten_numeric(prefix: str, value: Any, depth: int = 0, max_depth: int = 3) -> dict[str, float]:
    out: dict[str, float] = {}
    if depth > max_depth:
        return out
    if isinstance(value, bool):
        out[prefix] = float(value)
        return out
    if isinstance(value, (int, float)):
        out[prefix] = float(value)
        return out
    if isinstance(value, dict):
        for key in sorted(value):
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_numeric(next_prefix, value[key], depth + 1, max_depth))
    return out


def _hash_payload(payload: dict[str, Any]) -> str:
    packed = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()[:20]


def _ensure_columns(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return frame[columns]


def _write_table(conn, table_name: str, frame: pd.DataFrame) -> None:
    view_name = f"_tmp_{table_name}"
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.register(view_name, frame)
    conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM {view_name}")
    conn.unregister(view_name)


def build_readmodels(settings: Settings) -> BuildResult:
    warnings: list[str] = []

    decision_rows: list[dict[str, Any]] = []
    decision_intent_rows: list[dict[str, Any]] = []
    gate_block_rows: list[dict[str, Any]] = []
    entry_rejection_rows: list[dict[str, Any]] = []
    rejected_symbol_rows: list[dict[str, Any]] = []

    signal_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []

    raec_event_rows: list[dict[str, Any]] = []
    raec_allocation_rows: list[dict[str, Any]] = []
    raec_intent_rows: list[dict[str, Any]] = []
    raec_coordinator_rows: list[dict[str, Any]] = []

    slippage_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    risk_attr_rows: list[dict[str, Any]] = []

    backtest_run_rows: list[dict[str, Any]] = []
    backtest_metric_rows: list[dict[str, Any]] = []
    backtest_equity_rows: list[dict[str, Any]] = []

    freshness_rows: list[dict[str, Any]] = []

    decision_dates: list[str] = []
    signal_dates: list[str] = []

    sources = [
        SourceHealth(
            source_name="portfolio_decisions",
            source_glob=str(settings.ledger_dir / "PORTFOLIO_DECISIONS" / "*.jsonl"),
        ),
        SourceHealth(
            source_name="strategy_signals_s2",
            source_glob=str(settings.ledger_dir / "STRATEGY_SIGNALS" / S2_STRATEGY_ID / "*.jsonl"),
        ),
        SourceHealth(
            source_name="portfolio_risk_controls",
            source_glob=str(settings.ledger_dir / "PORTFOLIO_RISK_CONTROLS" / "*.jsonl"),
        ),
        SourceHealth(
            source_name="portfolio_throttle",
            source_glob=str(settings.ledger_dir / "PORTFOLIO_THROTTLE" / "*.jsonl"),
        ),
        SourceHealth(
            source_name="regime_e1",
            source_glob=str(settings.ledger_dir / "REGIME_E1" / "*.jsonl"),
        ),
        SourceHealth(
            source_name="raec_rebalance_events",
            source_glob=str(settings.ledger_dir / "RAEC_REBALANCE" / "**" / "*.jsonl"),
        ),
        SourceHealth(
            source_name="backtests_summary",
            source_glob=str(settings.backtests_dir / "**" / "summary.json"),
        ),
        SourceHealth(
            source_name="portfolio_decision_latest",
            source_glob=str(settings.state_dir / "portfolio_decision_latest.json"),
        ),
        SourceHealth(
            source_name="execution_slippage",
            source_glob=str(settings.ledger_dir / "EXECUTION_SLIPPAGE" / "*.jsonl"),
        ),
        SourceHealth(
            source_name="portfolio_snapshots",
            source_glob=str(settings.repo_root / "analytics" / "artifacts" / "portfolio_snapshots" / "*.json"),
        ),
    ]

    # PORTFOLIO_DECISIONS
    decision_source = sources[0]
    decision_files = sorted((settings.ledger_dir / "PORTFOLIO_DECISIONS").glob("*.jsonl"))
    decision_source.file_count = len(decision_files)
    if decision_files:
        decision_source.latest_mtime_utc = _iso_mtime(decision_files[-1])
    for path in decision_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001 - fail-open ingest
            decision_source.parse_status = "error"
            decision_source.last_error = str(exc)
            warnings.append(f"PORTFOLIO_DECISIONS parse error {path}: {exc}")
            continue
        decision_source.row_count += len(entries)
        for idx, rec in enumerate(entries):
            ny_date = str(rec.get("ny_date") or "")
            decision_id = str(rec.get("decision_id") or f"{path.name}:{idx}")
            decision_dates.append(ny_date)
            intents = rec.get("intents") or {}
            intents_meta = rec.get("intents_meta") or {}
            entry_rejections = intents_meta.get("entry_rejections") or {}
            gates = rec.get("gates") or {}
            market = gates.get("market") or {}
            mode = rec.get("mode") or {}

            decision_rows.append(
                {
                    "decision_id": decision_id,
                    "ny_date": ny_date,
                    "ts_utc": rec.get("ts_utc"),
                    "schema_version": str(rec.get("schema_version") or ""),
                    "execution_mode": mode.get("execution_mode"),
                    "dry_run_forced": bool(mode.get("dry_run_forced", False)),
                    "intent_count": int(intents.get("intent_count") or 0),
                    "entry_intents_created_count": int(intents_meta.get("entry_intents_created_count") or 0),
                    "accepted_count": int(entry_rejections.get("accepted") or 0),
                    "rejected_count": int(entry_rejections.get("rejected") or 0),
                    "candidates_seen": int(entry_rejections.get("candidates_seen") or 0),
                    "gate_block_count": len(gates.get("blocks") or []),
                    "market_is_open": bool(market.get("is_open", False)),
                    "live_gate_applied": bool(gates.get("live_gate_applied", False)),
                    "build_git_sha": (rec.get("build") or {}).get("git_sha"),
                    "source_file": str(path),
                    "record_index": idx,
                    "raw_json": json.dumps(rec, sort_keys=True, separators=(",", ":")),
                }
            )

            for block in gates.get("blocks") or []:
                gate_block_rows.append(
                    {
                        "decision_id": decision_id,
                        "ny_date": ny_date,
                        "ts_utc": rec.get("ts_utc"),
                        "block_code": str(block.get("code") or "unknown"),
                        "block_message": str(block.get("message") or ""),
                    }
                )

            for reason_code, rejected_count in sorted((entry_rejections.get("reason_counts") or {}).items()):
                entry_rejection_rows.append(
                    {
                        "decision_id": decision_id,
                        "ny_date": ny_date,
                        "ts_utc": rec.get("ts_utc"),
                        "reason_code": str(reason_code),
                        "rejected_count": int(rejected_count or 0),
                    }
                )

            for rejected in entry_rejections.get("rejected_symbols") or []:
                rejected_symbol_rows.append(
                    {
                        "decision_id": decision_id,
                        "ny_date": ny_date,
                        "ts_utc": rec.get("ts_utc"),
                        "symbol": str(rejected.get("symbol") or "").upper(),
                        "reason_code": str(rejected.get("reason") or ""),
                    }
                )

            for intent in intents.get("intents") or []:
                decision_intent_rows.append(
                    {
                        "decision_id": decision_id,
                        "ny_date": ny_date,
                        "ts_utc": rec.get("ts_utc"),
                        "strategy_id": str(intent.get("strategy_id") or DEFAULT_STRATEGY_ID),
                        "symbol": str(intent.get("symbol") or "").upper(),
                        "qty": float(intent.get("qty") or 0.0),
                        "side": str(intent.get("side") or "buy").lower(),
                    }
                )

    # STRATEGY_SIGNALS/S2
    signal_source = sources[1]
    signal_files = sorted((settings.ledger_dir / "STRATEGY_SIGNALS" / S2_STRATEGY_ID).glob("*.jsonl"))
    signal_source.file_count = len(signal_files)
    if signal_files:
        signal_source.latest_mtime_utc = _iso_mtime(signal_files[-1])
    for path in signal_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            signal_source.parse_status = "error"
            signal_source.last_error = str(exc)
            warnings.append(f"STRATEGY_SIGNALS parse error {path}: {exc}")
            continue
        signal_source.row_count += len(entries)
        for idx, rec in enumerate(entries):
            asof_date = str(rec.get("asof_date") or "")
            signal_dates.append(asof_date)
            signal_rows.append(
                {
                    "run_id": str(rec.get("run_id") or ""),
                    "asof_date": asof_date,
                    "strategy_id": str(rec.get("strategy_id") or ""),
                    "symbol": str(rec.get("symbol") or "").upper(),
                    "complex": rec.get("complex"),
                    "eligible": bool(rec.get("eligible", False)),
                    "selected": bool(rec.get("selected", False)),
                    "score": float(rec.get("score") or 0.0) if rec.get("score") is not None else None,
                    "reason_codes_json": json.dumps(rec.get("reason_codes") or [], sort_keys=True),
                    "gates_json": json.dumps(rec.get("gates") or {}, sort_keys=True),
                    "metrics_json": json.dumps(rec.get("metrics") or {}, sort_keys=True),
                    "source_file": str(path),
                    "record_index": idx,
                }
            )

    # PORTFOLIO_RISK_CONTROLS
    risk_source = sources[2]
    risk_files = sorted((settings.ledger_dir / "PORTFOLIO_RISK_CONTROLS").glob("*.jsonl"))
    risk_source.file_count = len(risk_files)
    if risk_files:
        risk_source.latest_mtime_utc = _iso_mtime(risk_files[-1])
    for path in risk_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            risk_source.parse_status = "error"
            risk_source.last_error = str(exc)
            warnings.append(f"PORTFOLIO_RISK_CONTROLS parse error {path}: {exc}")
            continue
        risk_source.row_count += len(entries)
        for rec in entries:
            controls = rec.get("risk_controls") or {}
            risk_rows.append(
                {
                    "source_type": "risk_controls",
                    "ny_date": str(rec.get("resolved_ny_date") or rec.get("requested_ny_date") or ""),
                    "as_of_utc": rec.get("as_of_utc"),
                    "record_type": rec.get("record_type"),
                    "regime_id": None,
                    "risk_multiplier": controls.get("risk_multiplier"),
                    "max_positions": controls.get("max_positions"),
                    "max_gross_exposure": controls.get("max_gross_exposure"),
                    "per_position_cap": controls.get("per_position_cap"),
                    "throttle_reason": controls.get("throttle_reason"),
                    "details_json": json.dumps(rec, sort_keys=True, separators=(",", ":")),
                    "source_file": str(path),
                }
            )

    # PORTFOLIO_THROTTLE
    throttle_source = sources[3]
    throttle_files = sorted((settings.ledger_dir / "PORTFOLIO_THROTTLE").glob("*.jsonl"))
    throttle_source.file_count = len(throttle_files)
    if throttle_files:
        throttle_source.latest_mtime_utc = _iso_mtime(throttle_files[-1])
    for path in throttle_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            throttle_source.parse_status = "error"
            throttle_source.last_error = str(exc)
            warnings.append(f"PORTFOLIO_THROTTLE parse error {path}: {exc}")
            continue
        throttle_source.row_count += len(entries)
        for rec in entries:
            throttle = rec.get("throttle") or {}
            risk_rows.append(
                {
                    "source_type": "throttle",
                    "ny_date": str(rec.get("resolved_ny_date") or rec.get("requested_ny_date") or ""),
                    "as_of_utc": rec.get("as_of_utc"),
                    "record_type": rec.get("record_type"),
                    "regime_id": rec.get("regime_id"),
                    "risk_multiplier": throttle.get("risk_multiplier"),
                    "max_positions": throttle.get("max_new_positions_multiplier"),
                    "max_gross_exposure": None,
                    "per_position_cap": None,
                    "throttle_reason": ",".join(throttle.get("reasons") or []),
                    "details_json": json.dumps(rec, sort_keys=True, separators=(",", ":")),
                    "source_file": str(path),
                }
            )

    # REGIME_E1
    regime_source = sources[4]
    regime_files = sorted((settings.ledger_dir / "REGIME_E1").glob("*.jsonl"))
    regime_source.file_count = len(regime_files)
    if regime_files:
        regime_source.latest_mtime_utc = _iso_mtime(regime_files[-1])
    for path in regime_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            regime_source.parse_status = "error"
            regime_source.last_error = str(exc)
            warnings.append(f"REGIME_E1 parse error {path}: {exc}")
            continue
        regime_source.row_count += len(entries)
        for rec in entries:
            regime_rows.append(
                {
                    "ny_date": str(rec.get("resolved_ny_date") or rec.get("ny_date") or rec.get("requested_ny_date") or ""),
                    "as_of_utc": rec.get("as_of_utc"),
                    "regime_id": rec.get("regime_id"),
                    "regime_label": rec.get("regime_label"),
                    "record_type": rec.get("record_type"),
                    "reason_codes_json": json.dumps(rec.get("reason_codes") or [], sort_keys=True),
                    "inputs_snapshot_json": json.dumps(rec.get("inputs_snapshot") or {}, sort_keys=True),
                    "source_file": str(path),
                }
            )

    # RAEC_REBALANCE
    raec_source = sources[5]
    raec_dir = settings.ledger_dir / "RAEC_REBALANCE"
    raec_files = sorted(raec_dir.glob("**/*.jsonl")) if raec_dir.exists() else []
    raec_source.file_count = len(raec_files)
    if raec_files:
        raec_source.latest_mtime_utc = _iso_mtime(raec_files[-1])
    for path in raec_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            raec_source.parse_status = "error"
            raec_source.last_error = str(exc)
            warnings.append(f"RAEC_REBALANCE parse error {path}: {exc}")
            continue
        raec_source.row_count += len(entries)
        for rec in entries:
            record_type = rec.get("record_type") or ""
            ny_date = str(rec.get("ny_date") or "")
            ts_utc = rec.get("ts_utc")
            strategy_id = str(rec.get("strategy_id") or "")

            if record_type == "RAEC_REBALANCE_EVENT":
                targets = rec.get("targets") or {}
                current_allocs = rec.get("current_allocations") or {}
                intents = rec.get("intents") or []

                raec_event_rows.append(
                    {
                        "event_id": _hash_payload(rec),
                        "ny_date": ny_date,
                        "ts_utc": ts_utc,
                        "strategy_id": strategy_id,
                        "book_id": str(rec.get("book_id") or ""),
                        "regime": str(rec.get("regime") or ""),
                        "should_rebalance": bool(rec.get("should_rebalance", False)),
                        "rebalance_trigger": str(rec.get("rebalance_trigger") or ""),
                        "intent_count": int(rec.get("intent_count") or 0),
                        "portfolio_vol_target": rec.get("portfolio_vol_target"),
                        "portfolio_vol_realized": rec.get("portfolio_vol_realized"),
                        "posted": bool(rec.get("posted", False)),
                        "notice": rec.get("notice"),
                        "signals_json": json.dumps(rec.get("signals") or {}, sort_keys=True),
                        "momentum_json": json.dumps(rec.get("momentum_scores") or [], sort_keys=True),
                        "targets_json": json.dumps(targets, sort_keys=True),
                        "current_json": json.dumps(current_allocs, sort_keys=True),
                        "source_file": str(path),
                    }
                )

                for symbol, weight in sorted(targets.items()):
                    raec_allocation_rows.append(
                        {
                            "ny_date": ny_date,
                            "strategy_id": strategy_id,
                            "alloc_type": "target",
                            "symbol": str(symbol).upper(),
                            "weight_pct": float(weight),
                        }
                    )

                for symbol, weight in sorted(current_allocs.items()):
                    raec_allocation_rows.append(
                        {
                            "ny_date": ny_date,
                            "strategy_id": strategy_id,
                            "alloc_type": "current",
                            "symbol": str(symbol).upper(),
                            "weight_pct": float(weight),
                        }
                    )

                for intent in intents:
                    raec_intent_rows.append(
                        {
                            "ny_date": ny_date,
                            "ts_utc": ts_utc,
                            "strategy_id": strategy_id,
                            "intent_id": str(intent.get("intent_id") or ""),
                            "symbol": str(intent.get("symbol") or "").upper(),
                            "side": str(intent.get("side") or "").upper(),
                            "delta_pct": float(intent.get("delta_pct") or 0.0),
                            "target_pct": float(intent.get("target_pct") or 0.0),
                            "current_pct": float(intent.get("current_pct") or 0.0),
                        }
                    )

            elif record_type == "RAEC_COORDINATOR_RUN":
                raec_coordinator_rows.append(
                    {
                        "ny_date": ny_date,
                        "ts_utc": ts_utc,
                        "capital_split_json": json.dumps(rec.get("capital_split") or {}, sort_keys=True),
                        "sub_results_json": json.dumps(rec.get("sub_strategy_results") or {}, sort_keys=True),
                    }
                )

    # BACKTESTS
    backtest_source = sources[6]
    summary_files = sorted(settings.backtests_dir.glob("**/summary.json")) if settings.backtests_dir.exists() else []
    backtest_source.file_count = len(summary_files)
    if summary_files:
        backtest_source.latest_mtime_utc = _iso_mtime(summary_files[-1])
    for path in summary_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            backtest_source.parse_status = "error"
            backtest_source.last_error = str(exc)
            warnings.append(f"BACKTEST summary parse error {path}: {exc}")
            continue
        backtest_source.row_count += 1

        run_rel = path.parent.relative_to(settings.backtests_dir).as_posix()
        run_id = run_rel.replace("/", "::")
        parts = run_rel.split("/")
        suite = parts[0] if parts else run_rel
        variant = "/".join(parts[1:]) if len(parts) > 1 else "default"

        eq_path = path.parent / "equity_curve.csv"
        tr_path = path.parent / "trades.csv"
        diag_path = path.parent / "scan_diagnostics.csv"

        backtest_run_rows.append(
            {
                "run_id": run_id,
                "suite": suite,
                "variant": variant,
                "summary_path": str(path),
                "summary_mtime_utc": _iso_mtime(path),
                "has_equity_curve": eq_path.exists(),
                "has_trades": tr_path.exists(),
                "has_scan_diagnostics": diag_path.exists(),
                "summary_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            }
        )

        metrics = _flatten_numeric("", payload)
        for metric_name, metric_value in sorted(metrics.items()):
            backtest_metric_rows.append(
                {
                    "run_id": run_id,
                    "metric_name": metric_name,
                    "metric_value": float(metric_value),
                }
            )

        if eq_path.exists():
            try:
                eq_frame = pd.read_csv(eq_path).head(1500)
                if not eq_frame.empty:
                    x_col = eq_frame.columns[0]
                    y_col = None
                    preferred = ["equity", "equity_curve", "portfolio_value", "value"]
                    for c in eq_frame.columns:
                        if c.lower() in preferred:
                            y_col = c
                            break
                    if y_col is None and len(eq_frame.columns) > 1:
                        y_col = eq_frame.columns[1]
                    if y_col is not None:
                        for i, row in eq_frame.iterrows():
                            y_val = row.get(y_col)
                            if y_val is None or (isinstance(y_val, float) and pd.isna(y_val)):
                                continue
                            try:
                                y_num = float(y_val)
                            except (TypeError, ValueError):
                                continue
                            backtest_equity_rows.append(
                                {
                                    "run_id": run_id,
                                    "point_index": int(i),
                                    "x_value": str(row.get(x_col)),
                                    "equity": y_num,
                                }
                            )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"BACKTEST equity parse warning {eq_path}: {exc}")

    # state/portfolio_decision_latest.json freshness only
    latest_source = sources[7]
    latest_file = settings.state_dir / "portfolio_decision_latest.json"
    if latest_file.exists():
        latest_source.file_count = 1
        latest_source.latest_mtime_utc = _iso_mtime(latest_file)
        try:
            payload = json.loads(latest_file.read_text(encoding="utf-8"))
            latest_source.row_count = 1
            # include as singleton row for quick UI check
            decision_rows.append(
                {
                    "decision_id": str(payload.get("decision_id") or "state_latest"),
                    "ny_date": str(payload.get("ny_date") or ""),
                    "ts_utc": payload.get("ts_utc"),
                    "schema_version": str(payload.get("schema_version") or ""),
                    "execution_mode": (payload.get("mode") or {}).get("execution_mode"),
                    "dry_run_forced": bool((payload.get("mode") or {}).get("dry_run_forced", False)),
                    "intent_count": int((payload.get("intents") or {}).get("intent_count") or 0),
                    "entry_intents_created_count": int(
                        (payload.get("intents_meta") or {}).get("entry_intents_created_count") or 0
                    ),
                    "accepted_count": int(
                        ((payload.get("intents_meta") or {}).get("entry_rejections") or {}).get("accepted") or 0
                    ),
                    "rejected_count": int(
                        ((payload.get("intents_meta") or {}).get("entry_rejections") or {}).get("rejected") or 0
                    ),
                    "candidates_seen": int(
                        ((payload.get("intents_meta") or {}).get("entry_rejections") or {}).get("candidates_seen")
                        or 0
                    ),
                    "gate_block_count": len(((payload.get("gates") or {}).get("blocks") or [])),
                    "market_is_open": bool(((payload.get("gates") or {}).get("market") or {}).get("is_open", False)),
                    "live_gate_applied": bool((payload.get("gates") or {}).get("live_gate_applied", False)),
                    "build_git_sha": ((payload.get("build") or {}).get("git_sha")),
                    "source_file": str(latest_file),
                    "record_index": -1,
                    "raw_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
                }
            )
        except Exception as exc:  # noqa: BLE001
            latest_source.parse_status = "error"
            latest_source.last_error = str(exc)
            warnings.append(f"STATE latest decision parse error {latest_file}: {exc}")

    # EXECUTION_SLIPPAGE
    slippage_source = sources[8]
    slippage_dir = settings.ledger_dir / "EXECUTION_SLIPPAGE"
    slippage_files = sorted(slippage_dir.glob("*.jsonl")) if slippage_dir.exists() else []
    slippage_source.file_count = len(slippage_files)
    if slippage_files:
        slippage_source.latest_mtime_utc = _iso_mtime(slippage_files[-1])
    for path in slippage_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            slippage_source.parse_status = "error"
            slippage_source.last_error = str(exc)
            warnings.append(f"EXECUTION_SLIPPAGE parse error {path}: {exc}")
            continue
        slippage_source.row_count += len(entries)
        for rec in entries:
            if rec.get("record_type") != "EXECUTION_SLIPPAGE":
                continue
            slippage_rows.append(
                {
                    "date_ny": str(rec.get("date_ny") or ""),
                    "symbol": str(rec.get("symbol") or "").upper(),
                    "strategy_id": str(rec.get("strategy_id") or ""),
                    "expected_price": rec.get("expected_price"),
                    "ideal_fill_price": rec.get("ideal_fill_price"),
                    "actual_fill_price": rec.get("actual_fill_price"),
                    "slippage_bps": rec.get("slippage_bps"),
                    "adv_shares_20d": rec.get("adv_shares_20d"),
                    "liquidity_bucket": rec.get("liquidity_bucket"),
                    "fill_ts_utc": rec.get("fill_ts_utc"),
                    "time_of_day_bucket": rec.get("time_of_day_bucket"),
                    "source_file": str(path),
                }
            )

    # PORTFOLIO_SNAPSHOTS
    snapshot_source = sources[9]
    snapshot_dir = settings.repo_root / "analytics" / "artifacts" / "portfolio_snapshots"
    snapshot_files = sorted(snapshot_dir.glob("*.json")) if snapshot_dir.exists() else []
    snapshot_source.file_count = len(snapshot_files)
    if snapshot_files:
        snapshot_source.latest_mtime_utc = _iso_mtime(snapshot_files[-1])
    for path in snapshot_files:
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            snapshot_source.parse_status = "error"
            snapshot_source.last_error = str(exc)
            warnings.append(f"PORTFOLIO_SNAPSHOTS parse error {path}: {exc}")
            continue
        snapshot_source.row_count += 1
        capital = payload.get("capital") or {}
        pnl = payload.get("pnl") or {}
        date_ny = str(payload.get("date_ny") or "")
        snapshot_rows.append(
            {
                "date_ny": date_ny,
                "run_id": payload.get("run_id"),
                "strategy_ids_json": json.dumps(payload.get("strategy_ids") or []),
                "capital_total": capital.get("total"),
                "capital_cash": capital.get("cash"),
                "capital_invested": capital.get("invested"),
                "gross_exposure": payload.get("gross_exposure"),
                "net_exposure": payload.get("net_exposure"),
                "realized_pnl": pnl.get("realized_today"),
                "unrealized_pnl": pnl.get("unrealized"),
                "fees_today": pnl.get("fees_today"),
                "source_file": str(path),
            }
        )
        for pos in payload.get("positions") or []:
            position_rows.append(
                {
                    "date_ny": date_ny,
                    "strategy_id": str(pos.get("strategy_id") or ""),
                    "symbol": str(pos.get("symbol") or "").upper(),
                    "qty": pos.get("qty"),
                    "avg_price": pos.get("avg_price"),
                    "mark_price": pos.get("mark_price"),
                    "notional": pos.get("notional"),
                }
            )

    # PORTFOLIO_RISK_ATTRIBUTION
    risk_attr_dir = settings.ledger_dir / "PORTFOLIO_RISK_ATTRIBUTION"
    risk_attr_files = sorted(risk_attr_dir.glob("*.jsonl")) if risk_attr_dir.exists() else []
    for path in risk_attr_files:
        try:
            entries = _iter_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"PORTFOLIO_RISK_ATTRIBUTION parse error {path}: {exc}")
            continue
        for rec in entries:
            risk_attr_rows.append(
                {
                    "date_ny": str(rec.get("date_ny") or ""),
                    "record_json": json.dumps(rec, sort_keys=True, separators=(",", ":")),
                    "source_file": str(path),
                }
            )

    for source in sources:
        freshness_rows.append(
            {
                "source_name": source.source_name,
                "source_glob": source.source_glob,
                "file_count": int(source.file_count),
                "row_count": int(source.row_count),
                "latest_mtime_utc": source.latest_mtime_utc,
                "parse_status": source.parse_status,
                "last_error": source.last_error,
            }
        )

    all_dates = [d for d in decision_dates + signal_dates if d]
    source_window = {
        "date_min": min(all_dates) if all_dates else None,
        "date_max": max(all_dates) if all_dates else None,
        "decision_records": len(decision_rows),
        "signal_records": len(signal_rows),
    }

    row_counts = {
        "decision_cycles": len(decision_rows),
        "decision_intents": len(decision_intent_rows),
        "decision_gate_blocks": len(gate_block_rows),
        "entry_rejections": len(entry_rejection_rows),
        "entry_rejected_symbols": len(rejected_symbol_rows),
        "strategy_signals": len(signal_rows),
        "risk_controls_daily": len(risk_rows),
        "regime_daily": len(regime_rows),
        "backtest_runs": len(backtest_run_rows),
        "backtest_metrics": len(backtest_metric_rows),
        "backtest_equity": len(backtest_equity_rows),
        "raec_rebalance_events": len(raec_event_rows),
        "raec_allocations": len(raec_allocation_rows),
        "raec_intents": len(raec_intent_rows),
        "raec_coordinator_runs": len(raec_coordinator_rows),
        "execution_slippage": len(slippage_rows),
        "portfolio_snapshots": len(snapshot_rows),
        "portfolio_positions": len(position_rows),
        "risk_attribution": len(risk_attr_rows),
        "freshness_health": len(freshness_rows),
    }

    data_version = _hash_payload(
        {
            "row_counts": row_counts,
            "freshness": freshness_rows,
            "source_window": source_window,
        }
    )
    as_of_utc = utc_now_iso()

    with connect_rw(settings.db_path) as conn:
        _write_table(
            conn,
            "decision_cycles",
            _ensure_columns(
                decision_rows,
                [
                    "decision_id",
                    "ny_date",
                    "ts_utc",
                    "schema_version",
                    "execution_mode",
                    "dry_run_forced",
                    "intent_count",
                    "entry_intents_created_count",
                    "accepted_count",
                    "rejected_count",
                    "candidates_seen",
                    "gate_block_count",
                    "market_is_open",
                    "live_gate_applied",
                    "build_git_sha",
                    "source_file",
                    "record_index",
                    "raw_json",
                ],
            ),
        )
        _write_table(
            conn,
            "decision_intents",
            _ensure_columns(
                decision_intent_rows,
                ["decision_id", "ny_date", "ts_utc", "strategy_id", "symbol", "qty", "side"],
            ),
        )
        _write_table(
            conn,
            "decision_gate_blocks",
            _ensure_columns(
                gate_block_rows,
                ["decision_id", "ny_date", "ts_utc", "block_code", "block_message"],
            ),
        )
        _write_table(
            conn,
            "entry_rejections",
            _ensure_columns(
                entry_rejection_rows,
                ["decision_id", "ny_date", "ts_utc", "reason_code", "rejected_count"],
            ),
        )
        _write_table(
            conn,
            "entry_rejected_symbols",
            _ensure_columns(
                rejected_symbol_rows,
                ["decision_id", "ny_date", "ts_utc", "symbol", "reason_code"],
            ),
        )
        _write_table(
            conn,
            "strategy_signals",
            _ensure_columns(
                signal_rows,
                [
                    "run_id",
                    "asof_date",
                    "strategy_id",
                    "symbol",
                    "complex",
                    "eligible",
                    "selected",
                    "score",
                    "reason_codes_json",
                    "gates_json",
                    "metrics_json",
                    "source_file",
                    "record_index",
                ],
            ),
        )
        _write_table(
            conn,
            "risk_controls_daily",
            _ensure_columns(
                risk_rows,
                [
                    "source_type",
                    "ny_date",
                    "as_of_utc",
                    "record_type",
                    "regime_id",
                    "risk_multiplier",
                    "max_positions",
                    "max_gross_exposure",
                    "per_position_cap",
                    "throttle_reason",
                    "details_json",
                    "source_file",
                ],
            ),
        )
        _write_table(
            conn,
            "regime_daily",
            _ensure_columns(
                regime_rows,
                [
                    "ny_date",
                    "as_of_utc",
                    "regime_id",
                    "regime_label",
                    "record_type",
                    "reason_codes_json",
                    "inputs_snapshot_json",
                    "source_file",
                ],
            ),
        )
        _write_table(
            conn,
            "raec_rebalance_events",
            _ensure_columns(
                raec_event_rows,
                [
                    "event_id",
                    "ny_date",
                    "ts_utc",
                    "strategy_id",
                    "book_id",
                    "regime",
                    "should_rebalance",
                    "rebalance_trigger",
                    "intent_count",
                    "portfolio_vol_target",
                    "portfolio_vol_realized",
                    "posted",
                    "notice",
                    "signals_json",
                    "momentum_json",
                    "targets_json",
                    "current_json",
                    "source_file",
                ],
            ),
        )
        _write_table(
            conn,
            "raec_allocations",
            _ensure_columns(
                raec_allocation_rows,
                ["ny_date", "strategy_id", "alloc_type", "symbol", "weight_pct"],
            ),
        )
        _write_table(
            conn,
            "raec_intents",
            _ensure_columns(
                raec_intent_rows,
                ["ny_date", "ts_utc", "strategy_id", "intent_id", "symbol", "side", "delta_pct", "target_pct", "current_pct"],
            ),
        )
        _write_table(
            conn,
            "raec_coordinator_runs",
            _ensure_columns(
                raec_coordinator_rows,
                ["ny_date", "ts_utc", "capital_split_json", "sub_results_json"],
            ),
        )
        _write_table(
            conn,
            "execution_slippage",
            _ensure_columns(
                slippage_rows,
                [
                    "date_ny",
                    "symbol",
                    "strategy_id",
                    "expected_price",
                    "ideal_fill_price",
                    "actual_fill_price",
                    "slippage_bps",
                    "adv_shares_20d",
                    "liquidity_bucket",
                    "fill_ts_utc",
                    "time_of_day_bucket",
                    "source_file",
                ],
            ),
        )
        _write_table(
            conn,
            "portfolio_snapshots",
            _ensure_columns(
                snapshot_rows,
                [
                    "date_ny",
                    "run_id",
                    "strategy_ids_json",
                    "capital_total",
                    "capital_cash",
                    "capital_invested",
                    "gross_exposure",
                    "net_exposure",
                    "realized_pnl",
                    "unrealized_pnl",
                    "fees_today",
                    "source_file",
                ],
            ),
        )
        _write_table(
            conn,
            "portfolio_positions",
            _ensure_columns(
                position_rows,
                ["date_ny", "strategy_id", "symbol", "qty", "avg_price", "mark_price", "notional"],
            ),
        )
        _write_table(
            conn,
            "risk_attribution",
            _ensure_columns(
                risk_attr_rows,
                ["date_ny", "record_json", "source_file"],
            ),
        )
        _write_table(
            conn,
            "backtest_runs",
            _ensure_columns(
                backtest_run_rows,
                [
                    "run_id",
                    "suite",
                    "variant",
                    "summary_path",
                    "summary_mtime_utc",
                    "has_equity_curve",
                    "has_trades",
                    "has_scan_diagnostics",
                    "summary_json",
                ],
            ),
        )
        _write_table(
            conn,
            "backtest_metrics",
            _ensure_columns(backtest_metric_rows, ["run_id", "metric_name", "metric_value"]),
        )
        _write_table(
            conn,
            "backtest_equity",
            _ensure_columns(backtest_equity_rows, ["run_id", "point_index", "x_value", "equity"]),
        )
        _write_table(
            conn,
            "freshness_health",
            _ensure_columns(
                freshness_rows,
                [
                    "source_name",
                    "source_glob",
                    "file_count",
                    "row_count",
                    "latest_mtime_utc",
                    "parse_status",
                    "last_error",
                ],
            ),
        )

        meta_rows = [
            {"key": "as_of_utc", "value": as_of_utc},
            {"key": "data_version", "value": data_version},
            {"key": "source_window", "value": json.dumps(source_window, sort_keys=True)},
            {"key": "warnings", "value": json.dumps(warnings, sort_keys=True)},
            {"key": "row_counts", "value": json.dumps(row_counts, sort_keys=True)},
        ]
        _write_table(conn, "readmodel_meta", pd.DataFrame(meta_rows))

    return BuildResult(
        as_of_utc=as_of_utc,
        data_version=data_version,
        source_window=source_window,
        warnings=warnings,
        row_counts=row_counts,
    )


def main() -> int:
    settings = Settings.from_env()
    result = build_readmodels(settings)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
