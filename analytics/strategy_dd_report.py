"""Per-sub-strategy drawdown report.

Reads the coordinator's RAEC_COORDINATOR_RUN ledger records, reconstructs
each sub-strategy's notional equity curve from its persisted targets plus
historical prices, and reports peak/current/max drawdown per strategy.

Usage:
    python -m analytics.strategy_dd_report
    python -m analytics.strategy_dd_report --since 2026-01-01 --threshold 0.12
    python -m analytics.strategy_dd_report --alert  # post Slack when any sub > threshold

The point: at age 51 the coordinator's fixed capital split (20/55/25)
makes no allowance for which sleeve is breaking. This report surfaces
the per-sleeve drawdown so the user can manually rebalance away from a
broken strategy — and forms the data foundation for an eventual
auto-throttle in the coordinator.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from alerts.slack import slack_alert
from data.prices import PriceProvider, get_default_price_provider

_LEDGER_DIR = Path("ledger") / "RAEC_REBALANCE" / "RAEC_401K_COORD"


@dataclass(frozen=True)
class SubStrategyDDReport:
    key: str
    days: int
    final_equity: float
    peak_equity: float
    current_dd: float
    max_dd: float
    max_dd_date: Optional[date]


def _iter_coordinator_records(repo_root: Path, since: Optional[date]) -> list[dict]:
    """Yield RAEC_COORDINATOR_RUN records from oldest to newest."""
    ledger_dir = repo_root / _LEDGER_DIR
    if not ledger_dir.exists():
        return []
    records: list[dict] = []
    for path in sorted(ledger_dir.glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if since is not None and day < since:
            continue
        with path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("record_type") != "RAEC_COORDINATOR_RUN":
                    continue
                records.append(rec)
    return records


def _symbol_returns_between(
    provider: PriceProvider, symbol: str, prev_day: date, day: date
) -> Optional[float]:
    """Return (close_day / close_prev_day - 1) or None if either close is missing."""
    series = dict(provider.get_daily_close_series(symbol))
    if prev_day not in series or day not in series:
        return None
    prev = series[prev_day]
    if prev <= 0:
        return None
    return series[day] / prev - 1.0


def _build_equity_curves(
    records: list[dict], provider: PriceProvider
) -> dict[str, list[tuple[date, float]]]:
    """Build per-sub-strategy notional equity curves from the records.

    Each record holds the targets in effect *as of that day*. The return
    between record N and N+1 is the weighted sum of symbol returns over
    that interval. Equity starts at 1.0 and compounds.
    """
    curves: dict[str, list[tuple[date, float]]] = {}
    if not records:
        return curves
    sub_keys = set()
    for rec in records:
        sub_keys.update((rec.get("sub_strategy_results") or {}).keys())
    for key in sub_keys:
        curves[key] = []

    prev_day: Optional[date] = None
    prev_targets: dict[str, dict[str, float]] = {}
    equity: dict[str, float] = {k: 1.0 for k in sub_keys}

    for rec in records:
        try:
            day = date.fromisoformat(rec["ny_date"])
        except (KeyError, ValueError):
            continue
        sub_results = rec.get("sub_strategy_results") or {}

        if prev_day is not None:
            for key in sub_keys:
                targets = prev_targets.get(key) or {}
                if not targets:
                    curves[key].append((day, equity[key]))
                    continue
                weighted = 0.0
                missing_weight = 0.0
                for symbol, pct in targets.items():
                    weight = pct / 100.0
                    ret = _symbol_returns_between(provider, symbol, prev_day, day)
                    if ret is None:
                        missing_weight += weight
                        continue
                    weighted += weight * ret
                if missing_weight > 0 and missing_weight < 1.0:
                    # Renormalize across the symbols we did get prices for.
                    weighted = weighted / (1.0 - missing_weight)
                equity[key] = equity[key] * (1.0 + weighted)
                curves[key].append((day, equity[key]))
        else:
            for key in sub_keys:
                curves[key].append((day, equity[key]))

        prev_day = day
        prev_targets = {
            k: (v.get("targets") or {}) for k, v in sub_results.items()
        }

    return curves


def _summarize_curve(key: str, curve: list[tuple[date, float]]) -> SubStrategyDDReport:
    if not curve:
        return SubStrategyDDReport(
            key=key, days=0, final_equity=1.0, peak_equity=1.0,
            current_dd=0.0, max_dd=0.0, max_dd_date=None,
        )
    peak = curve[0][1]
    max_dd = 0.0
    max_dd_date: Optional[date] = None
    for day, eq in curve:
        peak = max(peak, eq)
        dd = eq / peak - 1.0 if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
            max_dd_date = day
    final = curve[-1][1]
    current_dd = final / peak - 1.0 if peak > 0 else 0.0
    return SubStrategyDDReport(
        key=key,
        days=len(curve),
        final_equity=final,
        peak_equity=peak,
        current_dd=current_dd,
        max_dd=max_dd,
        max_dd_date=max_dd_date,
    )


def generate_report(
    *,
    repo_root: Path,
    since: Optional[date] = None,
    provider: PriceProvider | None = None,
) -> list[SubStrategyDDReport]:
    if provider is None:
        provider = get_default_price_provider(str(repo_root), period="5y")
    records = _iter_coordinator_records(repo_root, since)
    curves = _build_equity_curves(records, provider)
    return [
        _summarize_curve(key, curves[key]) for key in sorted(curves)
    ]


def print_report(reports: list[SubStrategyDDReport]) -> None:
    if not reports:
        print("No coordinator runs found.")
        return
    print(f"{'sub':<6} {'days':>5} {'final':>8} {'peak':>8} {'current_dd':>11} {'max_dd':>8} {'max_dd_on':>12}")
    print("-" * 62)
    for r in reports:
        print(
            f"{r.key:<6} {r.days:>5} {r.final_equity:>8.3f} {r.peak_equity:>8.3f} "
            f"{r.current_dd * 100:>10.1f}% {r.max_dd * 100:>7.1f}% "
            f"{str(r.max_dd_date) if r.max_dd_date else '':>12}"
        )


def alert_if_breached(reports: list[SubStrategyDDReport], threshold: float) -> int:
    """Post Slack alerts for any sub-strategy whose current DD breaches threshold.

    Returns the count of strategies that breached.
    """
    breached = [r for r in reports if r.current_dd < -abs(threshold)]
    if not breached:
        return 0
    msg_lines = [
        f"{r.key.upper()}: current_dd={r.current_dd * 100:.1f}%, "
        f"max_dd={r.max_dd * 100:.1f}% on {r.max_dd_date}"
        for r in breached
    ]
    slack_alert(
        "WARNING",
        f"RAEC sub-strategy drawdown >{abs(threshold) * 100:.0f}%",
        "\n".join(msg_lines),
        component="DDReport",
    )
    return len(breached)


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-sub-strategy drawdown report")
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--since",
        default=None,
        help="Only include coordinator runs on/after this NY date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.10,
        help="Alert threshold for current_dd (absolute, e.g. 0.10 = 10%%)",
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Post a Slack WARNING for any sub-strategy whose current_dd exceeds threshold",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    since = date.fromisoformat(args.since) if args.since else None
    reports = generate_report(repo_root=repo_root, since=since)
    print_report(reports)
    if args.alert:
        breached = alert_if_breached(reports, args.threshold)
        print(f"\n{breached} sub-strategies above DD threshold ({args.threshold * 100:.0f}%).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
