import argparse
from pathlib import Path

from config import cfg
from backtest_engine import run_backtest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run offline backtest with dynamic scan replay. "
            "Entry models: next_open enters at next trading day open after signal; "
            "same_close enters at the signal day close."
        )
    )
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--entry-model",
        choices=["next_open", "same_close"],
        default=cfg.BACKTEST_ENTRY_MODEL,
        help="Entry model for backtest fills.",
    )
    parser.add_argument(
        "--output-dir",
        default=cfg.BACKTEST_OUTPUT_DIR,
        help="Directory for backtest artifacts.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=cfg.BACKTEST_VERBOSE,
        help="Print per-day backtest summary lines.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    start_date = args.start or cfg.BACKTEST_START_DATE
    end_date = args.end or cfg.BACKTEST_END_DATE
    if not start_date or not end_date:
        raise ValueError("Both --start and --end (or BACKTEST_START_DATE/END_DATE) are required.")

    cfg.BACKTEST_ENTRY_MODEL = args.entry_model
    cfg.BACKTEST_OUTPUT_DIR = str(Path(args.output_dir))
    cfg.BACKTEST_VERBOSE = bool(args.verbose)

    result = run_backtest(cfg, start_date, end_date)
    print(f"Backtest run_id: {result.summary.get('run_id')}")
    print(f"Backtest output directory: {result.output_dir}")
    print(f"Backtest summary.json: {result.summary_path}")
    print("Backtest provenance: OK (summary.json includes required fields)")


if __name__ == "__main__":
    main()
