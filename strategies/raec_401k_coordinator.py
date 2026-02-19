"""RAEC 401(k) Multi-Strategy Coordinator — orchestrates V3, V4, V5."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from data.prices import PriceProvider, get_default_price_provider
from execution_v2 import book_ids, book_router
from execution_v2.schwab_manual_adapter import slack_post_enabled
from strategies import raec_401k_v3, raec_401k_v4, raec_401k_v5  # noqa: F401 — ensure registration
from strategies.raec_401k_base import BaseRAECStrategy
from strategies.raec_401k_registry import get as _get_strategy
from utils.atomic_write import atomic_write_text


BOOK_ID = book_ids.SCHWAB_401K_MANUAL
STRATEGY_ID = "RAEC_401K_COORD"
# Combined universe across all sub-strategies (for allocs compatibility)
DEFAULT_UNIVERSE = tuple(dict.fromkeys([
    *_get_strategy("RAEC_401K_V3").DEFAULT_UNIVERSE,
    *_get_strategy("RAEC_401K_V4").DEFAULT_UNIVERSE,
    *_get_strategy("RAEC_401K_V5").DEFAULT_UNIVERSE,
]))
FALLBACK_CASH_SYMBOL = "BIL"

DEFAULT_CAPITAL_SPLIT: dict[str, float] = {"v3": 0.40, "v4": 0.30, "v5": 0.30}

SUB_STRATEGIES: dict[str, BaseRAECStrategy] = {
    "v3": _get_strategy("RAEC_401K_V3"),
    "v4": _get_strategy("RAEC_401K_V4"),
    "v5": _get_strategy("RAEC_401K_V5"),
}


@dataclass(frozen=True)
class CoordinatorResult:
    asof_date: str
    sub_results: dict[str, object]
    capital_split: dict[str, float]
    rebalanced: list[str]
    posted: list[str]


def _state_path(repo_root: Path) -> Path:
    return repo_root / "state" / "strategies" / BOOK_ID / f"{STRATEGY_ID}.json"


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_state(path: Path, state: dict) -> None:
    payload = json.dumps(state, sort_keys=True, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, payload)


def _write_raec_ledger(
    coord_result: CoordinatorResult,
    *,
    repo_root: Path,
    build_git_sha: str | None = None,
) -> None:
    """Append a RAEC_COORDINATOR_RUN record to the coordinator's ledger."""
    ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / STRATEGY_ID
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{coord_result.asof_date}.jsonl"
    sub_strategy_results = {}
    for key, r in coord_result.sub_results.items():
        sub_strategy_results[key] = {
            "regime": r.regime,
            "should_rebalance": r.should_rebalance,
            "intent_count": len(r.intents),
            "posted": r.posted,
            "notice": r.notice,
        }
    record = {
        "record_type": "RAEC_COORDINATOR_RUN",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ny_date": coord_result.asof_date,
        "book_id": BOOK_ID,
        "strategy_id": STRATEGY_ID,
        "capital_split": coord_result.capital_split,
        "sub_strategy_results": sub_strategy_results,
        "rebalanced": coord_result.rebalanced,
        "posted": coord_result.posted,
        "build_git_sha": build_git_sha,
    }
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def run_coordinator(
    *,
    asof_date: str,
    repo_root: Path,
    price_provider: PriceProvider | None = None,
    dry_run: bool = False,
    capital_split: dict[str, float] | None = None,
    total_capital: float | None = None,
    post_enabled: bool | None = None,
    adapter_override: object | None = None,
) -> CoordinatorResult:
    provider = price_provider or get_default_price_provider(str(repo_root))
    split = capital_split or dict(DEFAULT_CAPITAL_SPLIT)
    cap = total_capital or 237_757.0

    # Run each sub-strategy with dry_run=True, allow_state_write=True
    sub_results: dict[str, object] = {}
    for key, strategy in SUB_STRATEGIES.items():
        pct = split.get(key, 0.0) * 100.0
        sub_cap = cap * split.get(key, 0.0)
        print(f"[COORD] Running {key.upper()} ({pct:.1f}% of portfolio = ${sub_cap:,.0f})...")
        result = strategy.run_strategy(
            asof_date=asof_date,
            repo_root=repo_root,
            price_provider=provider,
            dry_run=True,
            allow_state_write=True,
        )
        sub_results[key] = result

    # Post each sub-strategy's ticket independently
    posting_enabled = slack_post_enabled() if post_enabled is None else post_enabled
    rebalanced: list[str] = []
    posted: list[str] = []
    for key, result in sub_results.items():
        if result.should_rebalance:
            rebalanced.append(key)
            if not dry_run:
                adapter = adapter_override or book_router.select_trading_client(BOOK_ID)
                strategy = SUB_STRATEGIES[key]
                ticket_message = _build_sub_ticket(key=key, result=result, split=split, cap=cap)
                summary_intents = result.intents
                if not summary_intents:
                    summary_intents = [
                        {
                            "symbol": "NOTICE",
                            "side": "INFO",
                            "target_pct": 0.0,
                            "current_pct": 0.0,
                            "delta_pct": 0.0,
                            "strategy_id": strategy.STRATEGY_ID,
                            "intent_id": "coord-notice",
                        }
                    ]
                send_result = adapter.send_summary_ticket(
                    summary_intents,
                    message=ticket_message,
                    ny_date=asof_date,
                    repo_root=repo_root,
                    post_enabled=posting_enabled,
                )
                if send_result.sent > 0:
                    posted.append(key)

    # Post a "no trades" summary when nothing needs rebalancing
    if not rebalanced and not dry_run:
        adapter = adapter_override or book_router.select_trading_client(BOOK_ID)
        no_trade_message = _build_no_trades_message(
            asof_date=asof_date,
            sub_results=sub_results,
            split=split,
        )
        no_trade_intents = [
            {
                "symbol": "NOTICE",
                "side": "INFO",
                "target_pct": 0.0,
                "current_pct": 0.0,
                "delta_pct": 0.0,
                "strategy_id": STRATEGY_ID,
                "intent_id": f"coord-no-trades-{asof_date}",
            }
        ]
        send_result = adapter.send_summary_ticket(
            no_trade_intents,
            message=no_trade_message,
            ny_date=asof_date,
            repo_root=repo_root,
            post_enabled=posting_enabled,
        )
        if send_result.sent > 0:
            posted.append("no-trades-summary")

    # Print summary
    regime_parts = []
    for key in ("v3", "v4", "v5"):
        r = sub_results.get(key)
        regime_parts.append(f"{key.upper()}={r.regime}" if r else f"{key.upper()}=N/A")
    rebal_count = len(rebalanced)
    total_count = len(sub_results)
    print(f"\nCOORD Summary: {' '.join(regime_parts)} | {rebal_count}/{total_count} rebalancing")

    coord_result = CoordinatorResult(
        asof_date=asof_date,
        sub_results=sub_results,
        capital_split=split,
        rebalanced=rebalanced,
        posted=posted,
    )

    # Save coordinator state
    coord_state_path = _state_path(repo_root)
    coord_state = _load_state(coord_state_path)
    coord_state.update({
        "last_eval_date": asof_date,
        "capital_split": split,
        "sub_regimes": {key: r.regime for key, r in sub_results.items()},
        "sub_rebalanced": rebalanced,
    })
    _save_state(coord_state_path, coord_state)
    _write_raec_ledger(coord_result, repo_root=repo_root)

    return coord_result


def _build_no_trades_message(
    *,
    asof_date: str,
    sub_results: dict[str, object],
    split: dict[str, float],
) -> str:
    lines = [
        f"[COORD] No trades today ({asof_date})",
        "",
    ]
    for key in ("v3", "v4", "v5"):
        result = sub_results.get(key)
        if result:
            pct = split.get(key, 0.0) * 100.0
            lines.append(f"  {key.upper()} ({pct:.0f}%): regime={result.regime}, rebalance=No")
    lines.append("")
    lines.append("All positions aligned with targets.")
    return "\n".join(lines)


def _build_sub_ticket(
    *,
    key: str,
    result: object,
    split: dict[str, float],
    cap: float,
) -> str:
    pct = split.get(key, 0.0) * 100.0
    sub_cap = cap * split.get(key, 0.0)
    strategy = SUB_STRATEGIES[key]
    lines = [
        f"[COORD {key.upper()}] ({pct:.1f}% of portfolio = ${sub_cap:,.0f})",
        f"Strategy: {strategy.STRATEGY_ID}",
        f"Regime: {result.regime}",
    ]
    if result.intents:
        lines.append("Order intents (sells first):")
        for intent in result.intents:
            lines.append(
                f"  INTENT {intent['intent_id'][:12]}... | {intent['side']} {intent['symbol']} | "
                f"delta {intent['delta_pct']:.1f}% | target {intent['target_pct']:.1f}%"
            )
    else:
        lines.append("Order intents: none")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAEC 401(k) multi-strategy coordinator.")
    parser.add_argument("--asof", required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Skip Slack posts")
    parser.add_argument("--capital", type=float, default=None, help="Total portfolio capital")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    dry_run = args.dry_run or (os.getenv("DRY_RUN", "0") == "1")
    result = run_coordinator(
        asof_date=args.asof,
        repo_root=repo_root,
        dry_run=dry_run,
        total_capital=args.capital,
    )

    posted_count = len(result.posted)
    rebal_count = len(result.rebalanced)
    print(
        f"COORD: posted={posted_count} rebalanced={rebal_count} "
        f"asof={result.asof_date} dry_run={int(dry_run)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
