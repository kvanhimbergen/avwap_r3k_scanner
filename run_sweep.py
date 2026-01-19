import argparse
from pathlib import Path

from backtest_sweep import (
    build_params_from_cfg,
    load_sweep_spec,
    normalize_sweep_spec,
    parse_walk_forward_spec,
    run_sweep,
)
from config import cfg


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline backtest sweeps.")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--entry-model",
        choices=["next_open", "same_close"],
        default=cfg.BACKTEST_ENTRY_MODEL,
        help="Entry model for backtest fills.",
    )
    parser.add_argument("--sweep", help="Path to sweep spec JSON/YAML.")
    parser.add_argument(
        "--walk-forward",
        help="Walk-forward spec JSON string or path to JSON/YAML file.",
    )
    parser.add_argument(
        "--ohlcv-path",
        help="Single OHLCV history path for a sweep run.",
    )
    parser.add_argument(
        "--ohlcv-paths",
        help="Comma-separated OHLCV history paths for sweep mode.",
    )
    parser.add_argument(
        "--output-root",
        default=cfg.BACKTEST_OUTPUT_DIR,
        help="Output root for backtest artifacts.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    sweep_spec = None
    if args.sweep:
        sweep_spec = normalize_sweep_spec(load_sweep_spec(Path(args.sweep)))
    else:
        sweep_spec = {"base_params": build_params_from_cfg(cfg)}

    walk_forward_spec = parse_walk_forward_spec(args.walk_forward)

    ohlcv_paths = None
    if args.ohlcv_paths:
        ohlcv_paths = [Path(p.strip()) for p in args.ohlcv_paths.split(",") if p.strip()]
    if args.ohlcv_path:
        ohlcv_paths = [Path(args.ohlcv_path)]

    run_sweep(
        cfg=cfg,
        start_date=args.start,
        end_date=args.end,
        entry_model=args.entry_model,
        sweep_spec=sweep_spec,
        walk_forward_spec=walk_forward_spec,
        ohlcv_paths=ohlcv_paths,
        output_root=Path(args.output_root),
    )


if __name__ == "__main__":
    main()
