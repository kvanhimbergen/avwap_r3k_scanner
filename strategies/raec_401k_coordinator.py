"""RAEC 401(k) Multi-Strategy Coordinator — orchestrates V3, V4, V5."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from data.prices import PriceProvider, get_default_price_provider
from execution_v2 import book_ids, book_router
from execution_v2.schwab_manual_adapter import slack_post_enabled
from strategies import raec_401k_v3, raec_401k_v4, raec_401k_v5
from utils.atomic_write import atomic_write_text


BOOK_ID = book_ids.SCHWAB_401K_MANUAL
STRATEGY_ID = "RAEC_401K_COORD"
# Combined universe across all sub-strategies (for allocs compatibility)
DEFAULT_UNIVERSE = tuple(dict.fromkeys([
    *raec_401k_v3.DEFAULT_UNIVERSE, *raec_401k_v4.DEFAULT_UNIVERSE,
    *raec_401k_v5.DEFAULT_UNIVERSE,
]))
FALLBACK_CASH_SYMBOL = "BIL"

DEFAULT_CAPITAL_SPLIT: dict[str, float] = {"v3": 0.40, "v4": 0.30, "v5": 0.30}

SUB_STRATEGIES: dict[str, ModuleType] = {
    "v3": raec_401k_v3,
    "v4": raec_401k_v4,
    "v5": raec_401k_v5,
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
    for key, module in SUB_STRATEGIES.items():
        pct = split.get(key, 0.0) * 100.0
        sub_cap = cap * split.get(key, 0.0)
        print(f"[COORD] Running {key.upper()} ({pct:.1f}% of portfolio = ${sub_cap:,.0f})...")
        result = module.run_strategy(
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
                module = SUB_STRATEGIES[key]
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
                            "strategy_id": module.STRATEGY_ID,
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

    # Print summary
    regime_parts = []
    for key in ("v3", "v4", "v5"):
        r = sub_results.get(key)
        regime_parts.append(f"{key.upper()}={r.regime}" if r else f"{key.upper()}=N/A")
    rebal_count = len(rebalanced)
    total_count = len(sub_results)
    print(f"\nCOORD Summary: {' '.join(regime_parts)} | {rebal_count}/{total_count} rebalancing")

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

    return CoordinatorResult(
        asof_date=asof_date,
        sub_results=sub_results,
        capital_split=split,
        rebalanced=rebalanced,
        posted=posted,
    )


def _build_sub_ticket(
    *,
    key: str,
    result: object,
    split: dict[str, float],
    cap: float,
) -> str:
    pct = split.get(key, 0.0) * 100.0
    sub_cap = cap * split.get(key, 0.0)
    module = SUB_STRATEGIES[key]
    lines = [
        f"[COORD {key.upper()}] ({pct:.1f}% of portfolio = ${sub_cap:,.0f})",
        f"Strategy: {module.STRATEGY_ID}",
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
