"""RAEC 401(k) Strategy v1 (ETF-only, manual execution)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import stdev
from typing import Any, Iterable

from data.prices import PriceProvider, get_default_price_provider
from execution_v2 import book_ids, book_router
from execution_v2.schwab_manual_adapter import slack_post_enabled
from utils.atomic_write import atomic_write_text


BOOK_ID = book_ids.SCHWAB_401K_MANUAL
STRATEGY_ID = "RAEC_401K_V1"

DEFAULT_UNIVERSE = ("VTI", "SPY","QUAL", "MTUM", "VTV", "USMV", "BIL")
FALLBACK_CASH_SYMBOL = "BIL"

MIN_TRADE_PCT = 0.5
MAX_WEEKLY_TURNOVER_PCT = 10.0
DRIFT_THRESHOLD_PCT = 3.0


@dataclass(frozen=True)
class RegimeSignal:
    regime: str
    close: float
    sma50: float
    sma200: float
    vol_20d: float
    vol_252d: float
    trend_up: bool
    breadth_ok: bool
    vol_high: bool


@dataclass(frozen=True)
class RunResult:
    asof_date: str
    regime: str
    targets: dict[str, float]
    intents: list[dict]
    should_rebalance: bool
    posting_enabled: bool
    posted: bool
    notice: str | None


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
    result: RunResult,
    *,
    repo_root: Path,
    targets: dict[str, float],
    current_allocations: dict[str, float],
    signals: dict[str, Any],
    momentum_scores: list[dict[str, Any]],
    build_git_sha: str | None = None,
) -> None:
    """Append a RAEC_REBALANCE_EVENT record to the strategy's ledger."""
    ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / STRATEGY_ID
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{result.asof_date}.jsonl"
    record = {
        "record_type": "RAEC_REBALANCE_EVENT",
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "ny_date": result.asof_date,
        "book_id": BOOK_ID,
        "strategy_id": STRATEGY_ID,
        "regime": result.regime,
        "should_rebalance": result.should_rebalance,
        "rebalance_trigger": "monthly",
        "targets": targets,
        "current_allocations": current_allocations,
        "intent_count": len(result.intents),
        "intents": result.intents,
        "signals": signals,
        "momentum_scores": momentum_scores,
        "portfolio_vol_target": None,
        "portfolio_vol_realized": None,
        "posted": result.posted,
        "notice": result.notice,
        "build_git_sha": build_git_sha,
    }
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _round_pct(value: float) -> float:
    return round(float(value), 1)


def _intent_id(
    *,
    asof_date: str,
    symbol: str,
    side: str,
    target_pct: float,
) -> str:
    canonical = {
        "book_id": BOOK_ID,
        "strategy_id": STRATEGY_ID,
        "asof_date": asof_date,
        "symbol": symbol.upper(),
        "side": side.upper(),
        "target_pct": _round_pct(target_pct),
    }
    packed = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _get_cash_symbol(provider: PriceProvider) -> str:
    series = provider.get_daily_close_series("BIL")
    if series:
        return "BIL"
    return FALLBACK_CASH_SYMBOL


def _universe(cash_symbol: str) -> list[str]:
    symbols = [sym for sym in DEFAULT_UNIVERSE if sym != "BIL"]
    symbols.append(cash_symbol)
    return symbols


def _targets_for_regime(regime: str, cash_symbol: str) -> dict[str, float]:
    if regime == "RISK_ON":
        targets = {
            "VTI": 40.0,
            "QUAL": 25.0,
            "MTUM": 20.0,
            "VTV": 10.0,
            cash_symbol: 5.0,
        }
    elif regime == "TRANSITION":
        targets = {
            "VTI": 35.0,
            "QUAL": 25.0,
            "USMV": 20.0,
            "VTV": 10.0,
            cash_symbol: 10.0,
        }
    else:
        targets = {
            "USMV": 30.0,
            "VTV": 20.0,
            cash_symbol: 50.0,
        }
    return targets


def _sorted_series(series: Iterable[tuple[date, float]], *, asof: date) -> list[tuple[date, float]]:
    filtered = [(day, close) for day, close in series if day <= asof]
    filtered.sort(key=lambda item: item[0])
    return filtered


def _compute_volatility(returns: list[float]) -> float:
    if len(returns) < 2:
        raise ValueError("insufficient returns for volatility")
    return stdev(returns) * math.sqrt(252)


def _compute_signals(series: list[tuple[date, float]]) -> RegimeSignal:
    closes = [close for _, close in series]
    if len(closes) < 253:
        raise ValueError("insufficient price history for regime computation")
    sma200 = sum(closes[-200:]) / 200
    sma50 = sum(closes[-50:]) / 50
    close = closes[-1]
    returns = [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
    vol_20d = _compute_volatility(returns[-20:])
    vol_252d = _compute_volatility(returns[-252:])
    trend_up = close > sma200 and sma50 > sma200
    breadth_ok = close > sma200
    vol_high = vol_20d > vol_252d * 1.25
    if trend_up and breadth_ok and not vol_high:
        regime = "RISK_ON"
    elif breadth_ok and (vol_high or not trend_up):
        regime = "TRANSITION"
    else:
        regime = "RISK_OFF"
    return RegimeSignal(
        regime=regime,
        close=close,
        sma50=sma50,
        sma200=sma200,
        vol_20d=vol_20d,
        vol_252d=vol_252d,
        trend_up=trend_up,
        breadth_ok=breadth_ok,
        vol_high=vol_high,
    )


def _load_current_allocations(state: dict, universe: set[str]) -> tuple[dict[str, float] | None, str | None]:
    raw = state.get("last_known_allocations")
    if raw is None:
        return None, "no current allocs known"
    if not isinstance(raw, dict):
        return None, "no current allocs known"
    filtered = {}
    for symbol, pct in raw.items():
        symbol = str(symbol).upper()
        if symbol not in universe:
            continue
        filtered[symbol] = float(pct)
    return filtered, None


def _load_latest_csv_allocations(
    *,
    repo_root: Path,
    universe: set[str],
) -> dict[str, float] | None:
    if os.getenv("RAEC_AUTO_SYNC_ALLOCATIONS_FROM_CSV", "1").strip() not in {"1", "true", "TRUE", "yes", "YES"}:
        return None
    try:
        from strategies import raec_401k_allocs

        csv_path = raec_401k_allocs._latest_csv_in_directory(
            repo_root / raec_401k_allocs.DEFAULT_CSV_DROP_SUBDIR
        )
        parsed = raec_401k_allocs.parse_schwab_positions_csv(csv_path)
    except Exception:
        return None

    filtered: dict[str, float] = {}
    for symbol, pct in parsed.items():
        normalized = str(symbol).upper()
        if normalized not in universe:
            continue
        filtered[normalized] = float(pct)
    return filtered or None


def _compute_drift(current: dict[str, float], targets: dict[str, float]) -> dict[str, float]:
    drift = {}
    for symbol, target_pct in targets.items():
        current_pct = float(current.get(symbol, 0.0))
        drift[symbol] = target_pct - current_pct
    return drift


def _first_eval_of_month(asof: date, last_eval: str | None) -> bool:
    if not last_eval:
        return True
    prior = _parse_date(last_eval)
    return (prior.year, prior.month) != (asof.year, asof.month)


def _should_rebalance(
    *,
    asof: date,
    state: dict,
    regime: str,
    targets: dict[str, float],
    current_allocs: dict[str, float] | None,
) -> bool:
    if _first_eval_of_month(asof, state.get("last_eval_date")):
        return True
    if state.get("last_regime") and state.get("last_regime") != regime:
        return True
    if current_allocs is None:
        return False
    drift = _compute_drift(current_allocs, targets)
    return any(abs(delta) > DRIFT_THRESHOLD_PCT for delta in drift.values())


def _apply_turnover_cap(
    deltas: dict[str, float],
    *,
    max_weekly_turnover: float,
) -> dict[str, float]:
    buys = [delta for delta in deltas.values() if delta > 0]
    total_buys = sum(abs(delta) for delta in buys)
    if total_buys <= max_weekly_turnover or total_buys == 0:
        return deltas
    scale = max_weekly_turnover / total_buys
    return {symbol: delta * scale for symbol, delta in deltas.items()}


def _build_intents(
    *,
    asof_date: str,
    targets: dict[str, float],
    current: dict[str, float],
    min_trade_pct: float = MIN_TRADE_PCT,
    max_weekly_turnover: float = MAX_WEEKLY_TURNOVER_PCT,
) -> list[dict]:
    symbols = sorted(set(targets) | set(current))
    deltas = {symbol: targets.get(symbol, 0.0) - current.get(symbol, 0.0) for symbol in symbols}

    # Non-target holdings (present in current but not in targets) default to target=0.
    # Do NOT automatically liquidate them unless the drift is material.
    non_target_symbols = set(current) - set(targets)
    deltas = {
        symbol: delta
        for symbol, delta in deltas.items()
        if (symbol not in non_target_symbols) or (delta >= 0) or (abs(delta) >= DRIFT_THRESHOLD_PCT)
    }
    deltas = {symbol: delta for symbol, delta in deltas.items() if abs(delta) >= min_trade_pct}
    deltas = _apply_turnover_cap(deltas, max_weekly_turnover=max_weekly_turnover)
    deltas = {symbol: delta for symbol, delta in deltas.items() if abs(delta) >= min_trade_pct}
    intents = []
    for symbol, delta in deltas.items():
        side = "BUY" if delta > 0 else "SELL"
        target_pct = targets.get(symbol, 0.0)
        current_pct = current.get(symbol, 0.0)
        intents.append(
            {
                "symbol": symbol,
                "side": side,
                "delta_pct": delta,
                "target_pct": target_pct,
                "current_pct": current_pct,
                "strategy_id": STRATEGY_ID,
                "intent_id": _intent_id(
                    asof_date=asof_date,
                    symbol=symbol,
                    side=side,
                    target_pct=target_pct,
                ),
            }
        )
    sells = sorted((item for item in intents if item["side"] == "SELL"), key=lambda item: item["symbol"])
    buys = sorted((item for item in intents if item["side"] == "BUY"), key=lambda item: item["symbol"])
    return sells + buys


def _format_signal_block(signal: RegimeSignal) -> str:
    return (
        "Signals: "
        f"SMA200={signal.sma200:.2f}, SMA50={signal.sma50:.2f}, "
        f"vol20={signal.vol_20d:.4f}, vol252={signal.vol_252d:.4f}"
    )


def _build_ticket_message(
    *,
    asof_date: str,
    regime: str,
    signal: RegimeSignal,
    intents: list[dict],
    notice: str | None,
) -> str:
    lines = [
        "RAEC 401(k) Manual Rebalance Ticket",
        f"Strategy: {STRATEGY_ID}",
        f"Book: {BOOK_ID}",
        f"As-of (NY): {asof_date}",
        f"Regime: {regime}",
        _format_signal_block(signal),
    ]
    if notice:
        lines.append(f"NOTICE: {notice}")
    lines.append("")
    if intents:
        lines.append("Order intents (sells first):")
        for intent in intents:
            lines.append(
                "INTENT "
                f"{intent['intent_id']} | {intent['side']} {intent['symbol']} | "
                f"delta {intent['delta_pct']:.1f}% | "
                f"target {intent['target_pct']:.1f}% | "
                f"current {intent['current_pct']:.1f}%"
            )
    else:
        lines.append("Order intents: none (allocations at target or missing current allocs).")
    lines.append("")
    lines.append("Checklist:")
    lines.append("- [ ] Review allocations and confirm drift/regime.")
    lines.append("- [ ] Execute trades manually in Schwab 401(k) if required.")
    lines.append("- [ ] Reply with execution status + intent_id.")
    lines.append("")
    lines.append("Reply protocol: EXECUTED / PARTIAL / SKIPPED / ERROR with intent_id.")
    return "\n".join(lines)


def run_strategy(
    *,
    asof_date: str,
    repo_root: Path,
    price_provider: PriceProvider | None = None,
    dry_run: bool = False,
    allow_state_write: bool = False,
    post_enabled: bool | None = None,
    adapter_override: object | None = None,
) -> RunResult:
    provider = price_provider or get_default_price_provider(str(repo_root))
    cash_symbol = _get_cash_symbol(provider)
    universe = _universe(cash_symbol)
    universe_set = set(universe)

    vti_series = _sorted_series(provider.get_daily_close_series("VTI"), asof=_parse_date(asof_date))
    signal = _compute_signals(vti_series)
    targets = _targets_for_regime(signal.regime, cash_symbol)

    state_path = _state_path(repo_root)
    state = _load_state(state_path)

    current_allocs = _load_latest_csv_allocations(repo_root=repo_root, universe=universe_set)
    notice = None
    if current_allocs is None:
        current_allocs, notice = _load_current_allocations(state, universe_set)
    if current_allocs is None:
        current_allocs = {symbol: targets[symbol] for symbol in targets}
    should_rebalance = _should_rebalance(
        asof=_parse_date(asof_date),
        state=state,
        regime=signal.regime,
        targets=targets,
        current_allocs=None if notice else current_allocs,
    )

    # If we can't load current allocations, still emit an informational ticket.
    if notice:
        should_rebalance = True

    intents: list[dict] = []
    if should_rebalance and not notice:
        intents = _build_intents(asof_date=asof_date, targets=targets, current=current_allocs)

    ticket_message = _build_ticket_message(
        asof_date=asof_date,
        regime=signal.regime,
        signal=signal,
        intents=intents,
        notice=notice,
    )

    posting_enabled = slack_post_enabled() if post_enabled is None else post_enabled
    posted = False
    if should_rebalance:
        if dry_run:
            print(ticket_message)
        else:
            adapter = adapter_override or book_router.select_trading_client(BOOK_ID)
            summary_intents = intents
            if not intents:
                summary_intents = [
                    {
                        "symbol": "NOTICE",
                        "side": "INFO",
                        "target_pct": 0.0,
                        "current_pct": 0.0,
                        "delta_pct": 0.0,
                        "strategy_id": STRATEGY_ID,
                        "intent_id": _intent_id(
                            asof_date=asof_date,
                            symbol="NOTICE",
                            side="INFO",
                            target_pct=0.0,
                        ),
                    }
                ]
            result = adapter.send_summary_ticket(
                summary_intents,
                message=ticket_message,
                ny_date=asof_date,
                repo_root=repo_root,
                post_enabled=posting_enabled,
            )
            posted = result.sent > 0

    run_result = RunResult(
        asof_date=asof_date,
        regime=signal.regime,
        targets=targets,
        intents=intents,
        should_rebalance=should_rebalance,
        posting_enabled=posting_enabled,
        posted=posted,
        notice=notice,
    )

    if not dry_run or allow_state_write:
        state.update(
            {
                "last_eval_date": asof_date,
                "last_regime": signal.regime,
                "last_targets": targets,
            }
        )
        if notice is None:
            state["last_known_allocations"] = current_allocs
        _save_state(state_path, state)
        _write_raec_ledger(
            run_result,
            repo_root=repo_root,
            targets=targets,
            current_allocations=current_allocs,
            signals={
                "close": signal.close,
                "sma50": signal.sma50,
                "sma200": signal.sma200,
                "vol_20d": signal.vol_20d,
                "vol_252d": signal.vol_252d,
                "trend_up": signal.trend_up,
                "breadth_ok": signal.breadth_ok,
                "vol_high": signal.vol_high,
            },
            momentum_scores=[],
        )

    return run_result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAEC 401(k) manual strategy.")
    parser.add_argument("--asof", required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Skip Slack post and ledger write")
    parser.add_argument(
        "--allow-state-write",
        action="store_true",
        default=False,
        help="Allow state updates even in dry-run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    dry_run = args.dry_run or (os.getenv("DRY_RUN", "0") == "1")
    result = run_strategy(
        asof_date=args.asof,
        repo_root=repo_root,
        dry_run=dry_run,
        allow_state_write=args.allow_state_write,
    )

    # --- Structured summary (stable grep target) ---
    tickets_sent = 1 if result.posted else 0

    if result.posted:
        reason = "sent"
    elif not result.should_rebalance:
        reason = "notice_blocked" if result.notice else "no_rebalance_needed"
    elif dry_run:
        reason = "dry_run"
    elif not result.posting_enabled:
        reason = "posting_disabled"
    else:
        reason = "idempotent_or_adapter_skipped"

    notice_str = (result.notice or "none").replace("\n", " ").strip()

    print(
        "SCHWAB_401K_MANUAL: "
        f"tickets_sent={tickets_sent} "
        f"asof={result.asof_date} "
        f"should_rebalance={int(result.should_rebalance)} "
        f"posting_enabled={int(result.posting_enabled)} "
        f"posted={int(result.posted)} "
        f"reason={reason} "
        f"notice={notice_str}"
    )




if __name__ == "__main__":
    raise SystemExit(main())
