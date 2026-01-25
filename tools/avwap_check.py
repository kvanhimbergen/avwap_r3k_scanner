from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class CheckResult:
    status: str
    name: str
    message: str


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None


def _ensure_dir_exists(path: Path) -> Optional[str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - safety net
        return f"unable to create directory: {exc}"
    return None


def _write_probe_file(path: Path) -> Optional[str]:
    probe = path / ".avwap_check_tmp"
    try:
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        return f"not writable: {exc}"
    return None


def _summarize_output(stdout: str, stderr: str) -> str:
    chunks: List[str] = []
    if stdout.strip():
        chunks.append(f"stdout={stdout.strip().replace(os.linesep, ' | ')}")
    if stderr.strip():
        chunks.append(f"stderr={stderr.strip().replace(os.linesep, ' | ')}")
    return " ".join(chunks) if chunks else "no output"


def _run_execution_config_check(base_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("LIVE_TRADING", None)
    if env.get("DRY_RUN", "").strip() == "1" and not env.get("EXECUTION_MODE"):
        env["EXECUTION_MODE"] = "DRY_RUN"
    cmd = [sys.executable, "-m", "execution_v2.execution_main", "--config-check"]
    return subprocess.run(
        cmd,
        cwd=str(base_dir),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _resolve_db_path(base_dir: Path, db_path: Optional[str]) -> Path:
    if db_path:
        return Path(db_path)
    default_path = os.getenv("EXECUTION_V2_DB", "data/execution_v2.sqlite")
    return (base_dir / default_path).resolve()


def _check_repo_root(base_dir: Path) -> CheckResult:
    expected = [base_dir / "docs", base_dir / "execution_v2"]
    missing = sorted(str(path.relative_to(base_dir)) for path in expected if not path.exists())
    if missing:
        return CheckResult(
            status="FAIL",
            name="repo_root",
            message=f"missing expected paths: {', '.join(missing)}",
        )
    return CheckResult(status="PASS", name="repo_root", message="repo root looks valid")


def _check_required_dir(name: str, path: Path) -> CheckResult:
    failure = _ensure_dir_exists(path)
    if failure:
        return CheckResult(status="FAIL", name=name, message=f"{path}: {failure}")
    writable = _write_probe_file(path)
    if writable:
        return CheckResult(status="FAIL", name=name, message=f"{path}: {writable}")
    return CheckResult(status="PASS", name=name, message=f"{path}: ok")


def _check_execution_config(base_dir: Path) -> CheckResult:
    proc = _run_execution_config_check(base_dir)
    if proc.returncode != 0:
        summary = _summarize_output(proc.stdout, proc.stderr)
        return CheckResult(
            status="FAIL",
            name="execution_config_check",
            message=f"config-check failed (exit {proc.returncode}): {summary}",
        )
    return CheckResult(status="PASS", name="execution_config_check", message="config-check passed")


def _check_systemd_unit() -> CheckResult:
    proc = subprocess.run(
        ["systemctl", "cat", "execution.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        summary = _summarize_output(proc.stdout, proc.stderr)
        return CheckResult(
            status="WARN",
            name="systemd_unit",
            message=f"execution.service not found: {summary}",
        )
    return CheckResult(status="PASS", name="systemd_unit", message="execution.service is present")


def _check_systemd_dropins() -> CheckResult:
    dropin_paths = [
        Path("/etc/systemd/system/execution.service.d"),
        Path("/usr/lib/systemd/system/execution.service.d"),
        Path("/lib/systemd/system/execution.service.d"),
    ]
    exists = any(path.exists() for path in dropin_paths)
    if not exists:
        return CheckResult(
            status="WARN",
            name="systemd_dropins",
            message="execution.service.d drop-ins not found",
        )
    return CheckResult(status="PASS", name="systemd_dropins", message="drop-ins detected")


def _check_watchlist(base_dir: Path) -> CheckResult:
    watchlist = base_dir / "tradingview_watchlist.txt"
    if not watchlist.exists():
        return CheckResult(
            status="WARN",
            name="watchlist",
            message="tradingview_watchlist.txt not found",
        )
    return CheckResult(status="PASS", name="watchlist", message="watchlist present")


def _check_daily_candidates_parent(base_dir: Path) -> CheckResult:
    parent = (base_dir / "daily_candidates.csv").parent
    if os.access(parent, os.W_OK):
        return CheckResult(
            status="PASS",
            name="daily_candidates_parent",
            message=f"{parent} is writable",
        )
    return CheckResult(
        status="WARN",
        name="daily_candidates_parent",
        message=f"{parent} is not writable",
    )


def _check_backtest_cache(base_dir: Path) -> CheckResult:
    cache_file = base_dir / "cache" / "ohlcv_history.parquet"
    if not cache_file.exists():
        return CheckResult(
            status="WARN",
            name="backtest_cache",
            message="cache/ohlcv_history.parquet not found",
        )
    return CheckResult(status="PASS", name="backtest_cache", message="ohlcv history cache present")


def _check_universe_snapshot(base_dir: Path) -> CheckResult:
    snapshot = base_dir / "universe" / "snapshots" / "iwv_holdings_latest.csv"
    if not snapshot.exists():
        return CheckResult(
            status="WARN",
            name="universe_snapshot",
            message="universe snapshot not found",
        )
    return CheckResult(status="PASS", name="universe_snapshot", message="universe snapshot present")


def _check_backtests_dir(base_dir: Path) -> CheckResult:
    backtests_dir = base_dir / "backtests"
    try:
        backtests_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return CheckResult(
            status="WARN",
            name="backtests_dir",
            message=f"unable to create backtests/: {exc}",
        )
    if os.access(backtests_dir, os.W_OK):
        return CheckResult(status="PASS", name="backtests_dir", message="backtests/ is writable")
    return CheckResult(status="WARN", name="backtests_dir", message="backtests/ is not writable")


def _collect_results(args: argparse.Namespace) -> List[CheckResult]:
    results: List[CheckResult] = []
    base_dir = Path(args.base_dir).resolve()
    state_dir = Path(args.state_dir).resolve()
    ledger_dir = Path(args.ledger_dir).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    _resolve_db_path(base_dir, args.db_path)

    results.append(_check_repo_root(base_dir))
    results.append(_check_required_dir("state_dir", state_dir))
    results.append(_check_required_dir("ledger_dir", ledger_dir))
    results.append(_check_required_dir("cache_dir", cache_dir))

    if args.mode in {"execution", "all"}:
        results.append(_check_execution_config(base_dir))
        if _is_linux() and _systemctl_available():
            results.append(_check_systemd_unit())
            results.append(_check_systemd_dropins())

    if args.mode in {"scan", "all"}:
        results.append(_check_watchlist(base_dir))
        results.append(_check_daily_candidates_parent(base_dir))

    if args.mode in {"backtest", "all"}:
        results.append(_check_backtest_cache(base_dir))
        results.append(_check_universe_snapshot(base_dir))
        results.append(_check_backtests_dir(base_dir))

    return results


def _determine_result(results: Iterable[CheckResult], strict: bool) -> tuple[str, int]:
    has_fail = any(result.status == "FAIL" for result in results)
    has_warn = any(result.status == "WARN" for result in results)
    if has_fail:
        return "FAIL", 1
    if has_warn:
        return ("FAIL", 1) if strict else ("WARN", 2)
    return "PASS", 0


def _render_human(results: List[CheckResult], result: str, exit_code: int) -> str:
    lines: List[str] = []
    for status in ("PASS", "WARN", "FAIL"):
        lines.append(status)
        for item in results:
            if item.status == status:
                lines.append(f"- {item.name}: {item.message}")
        lines.append("")
    lines.append(f"RESULT={result} EXIT_CODE={exit_code}")
    return "\n".join(lines)


def _render_json(results: List[CheckResult], result: str, exit_code: int, args: argparse.Namespace) -> str:
    payload = {
        "base_dir": str(Path(args.base_dir).resolve()),
        "exit_code": exit_code,
        "mode": args.mode,
        "result": result,
        "strict": bool(args.strict),
        "checks": [
            {"message": item.message, "name": item.name, "status": item.status}
            for item in results
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AVWAP offline preflight checks")
    parser.add_argument(
        "--mode",
        choices=["execution", "scan", "backtest", "all"],
        default="all",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--base-dir", default=str(Path.cwd()))
    parser.add_argument("--state-dir")
    parser.add_argument("--ledger-dir")
    parser.add_argument("--cache-dir")
    parser.add_argument("--db-path")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    base_dir = Path(args.base_dir).resolve()
    args.state_dir = args.state_dir or str(base_dir / "state")
    args.ledger_dir = args.ledger_dir or str(base_dir / "ledger")
    args.cache_dir = args.cache_dir or str(base_dir / "cache")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        results = _collect_results(args)
    except Exception as exc:  # pragma: no cover - safety net
        results = [
            CheckResult(status="FAIL", name="avwap_check", message=f"unexpected error: {exc}")
        ]
    result, exit_code = _determine_result(results, args.strict)
    output = _render_json(results, result, exit_code, args) if args.json else _render_human(
        results, result, exit_code
    )
    print(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
