from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import backtest_engine
from config import cfg
from portfolio.risk_controls import FEATURE_FLAG_ENV


def _atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _summary_slice(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "exposure_avg_pct": summary.get("exposure_avg_pct"),
        "max_concurrent_positions": summary.get("max_concurrent_positions"),
        "avg_position_size": summary.get("avg_position_size"),
        "total_trades": summary.get("total_trades"),
        "final_equity": summary.get("final_equity"),
        "run_id": summary.get("run_id"),
    }


def _numeric_diff(value_a: Any, value_b: Any) -> Any:
    try:
        return float(value_b) - float(value_a)
    except (TypeError, ValueError):
        return None


def _run_backtest(
    *,
    output_dir: Path,
    risk_modulation_enabled: bool,
    start_date: str | date | datetime,
    end_date: str | date | datetime,
    universe_symbols: list[str] | None,
) -> backtest_engine.BacktestResult:
    original_output_dir = getattr(cfg, "BACKTEST_OUTPUT_DIR", None)
    original_flag = os.getenv(FEATURE_FLAG_ENV)

    os.environ[FEATURE_FLAG_ENV] = "1" if risk_modulation_enabled else "0"
    cfg.BACKTEST_OUTPUT_DIR = str(output_dir)
    try:
        result = backtest_engine.run_backtest(
            cfg,
            start_date,
            end_date,
            universe_symbols=universe_symbols,
        )
    finally:
        if original_output_dir is None:
            if hasattr(cfg, "BACKTEST_OUTPUT_DIR"):
                delattr(cfg, "BACKTEST_OUTPUT_DIR")
        else:
            cfg.BACKTEST_OUTPUT_DIR = original_output_dir
        if original_flag is None:
            os.environ.pop(FEATURE_FLAG_ENV, None)
        else:
            os.environ[FEATURE_FLAG_ENV] = original_flag
    return result


def run_regime_risk_simulation(
    *,
    start_date: str | date | datetime,
    end_date: str | date | datetime,
    output_dir: Path,
    universe_symbols: list[str] | None = None,
) -> Path:
    baseline_dir = output_dir / "baseline"
    modulated_dir = output_dir / "modulated"

    baseline = _run_backtest(
        output_dir=baseline_dir,
        risk_modulation_enabled=False,
        start_date=start_date,
        end_date=end_date,
        universe_symbols=universe_symbols,
    )
    modulated = _run_backtest(
        output_dir=modulated_dir,
        risk_modulation_enabled=True,
        start_date=start_date,
        end_date=end_date,
        universe_symbols=universe_symbols,
    )

    baseline_summary = _summary_slice(baseline.summary)
    modulated_summary = _summary_slice(modulated.summary)

    comparison = {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "baseline": baseline_summary,
        "modulated": modulated_summary,
        "diff": {
            "exposure_avg_pct": _numeric_diff(
                baseline_summary.get("exposure_avg_pct"),
                modulated_summary.get("exposure_avg_pct"),
            ),
            "max_concurrent_positions": _numeric_diff(
                baseline_summary.get("max_concurrent_positions"),
                modulated_summary.get("max_concurrent_positions"),
            ),
            "avg_position_size": _numeric_diff(
                baseline_summary.get("avg_position_size"),
                modulated_summary.get("avg_position_size"),
            ),
            "total_trades": _numeric_diff(
                baseline_summary.get("total_trades"),
                modulated_summary.get("total_trades"),
            ),
            "final_equity": _numeric_diff(
                baseline_summary.get("final_equity"),
                modulated_summary.get("final_equity"),
            ),
        },
    }

    output_path = output_dir / f"compare_{start_date}_{end_date}.json"
    _atomic_write_json(comparison, output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run offline backtest comparison with and without regime risk modulation",
    )
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--output-dir",
        default="backtests/regime_risk_modulation",
        help="Output directory for comparison summary",
    )
    parser.add_argument(
        "--universe-symbol",
        action="append",
        dest="universe_symbols",
        help="Optional universe symbol override (repeatable)",
    )
    args = parser.parse_args()

    output_path = run_regime_risk_simulation(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=Path(args.output_dir),
        universe_symbols=args.universe_symbols,
    )

    print(f"comparison_summary={output_path}")


if __name__ == "__main__":
    main()
