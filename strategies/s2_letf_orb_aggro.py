"""S2_LETF_ORB_AGGRO candidate producer (aggressive, auditable, offline-first)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd

from execution_v2 import book_ids
from execution_v2.strategy_registry import StrategyID
from utils.atomic_write import atomic_write_text


BOOK_ID = book_ids.SCHWAB_401K_MANUAL
STRATEGY_ID = StrategyID.S2_LETF_ORB_AGGRO.value

LEVERAGED_UNIVERSE = (
    "TQQQ",
    "SOXL",
    "SPXL",
    "TECL",
    "FNGU",
    "NVDL",
    "UPRO",
    "SSO",
    "QLD",
    "USD",
    "ROM",
    "TNA",
    "FAS",
    "LABU",
    "WEBL",
    "DUSL",
    "CURE",
    "NAIL",
    "BULZ",
    "FNGO",
)

EXPANDED_UNIVERSE = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AVGO",
    "META",
    "AMZN",
    "GOOGL",
    "NFLX",
    "TSLA",
    "MSTR",
    "COIN",
    "SMCI",
    "PLTR",
    "PANW",
    "ANET",
    "MU",
    "CRM",
    "UBER",
    "SNOW",
    "RIVN",
    "SHOP",
    "INTC",
    "ORCL",
    "ADBE",
    "NOW",
    "FTNT",
    "CRWD",
    "MDB",
    "DDOG",
    "NET",
)

DEFAULT_UNIVERSE = tuple(dict.fromkeys(LEVERAGED_UNIVERSE + EXPANDED_UNIVERSE))

UNIVERSE_PROFILES: dict[str, tuple[str, ...]] = {
    "leveraged_only": LEVERAGED_UNIVERSE,
    "aggressive_expanded": DEFAULT_UNIVERSE,
}

COMPLEX_BY_SYMBOL = {
    "TQQQ": "ndx",
    "QLD": "ndx",
    "ROM": "ndx",
    "TECL": "ndx",
    "BULZ": "ndx",
    "SOXL": "semi",
    "USD": "semi",
    "NVDL": "single_name_tech",
    "FNGU": "internet_platform",
    "FNGO": "internet_platform",
    "SPXL": "spx",
    "UPRO": "spx",
    "SSO": "spx",
    "TNA": "small_cap",
    "FAS": "financials",
    "LABU": "biotech",
    "CURE": "healthcare",
    "WEBL": "internet",
    "DUSL": "industrials",
    "NAIL": "housing",
    "SPY": "broad_index",
    "QQQ": "ndx",
    "IWM": "small_cap",
    "DIA": "dow",
    "AAPL": "mega_cap_tech",
    "MSFT": "mega_cap_tech",
    "NVDA": "ai_semis",
    "AMD": "ai_semis",
    "AVGO": "ai_semis",
    "META": "internet_platform",
    "AMZN": "internet_platform",
    "GOOGL": "internet_platform",
    "NFLX": "internet_platform",
    "TSLA": "ev_high_beta",
    "MSTR": "crypto_beta",
    "COIN": "crypto_beta",
    "SMCI": "ai_hardware",
    "PLTR": "ai_software",
    "PANW": "security_growth",
    "ANET": "networking_growth",
    "MU": "memory_semis",
    "CRM": "enterprise_software",
    "UBER": "mobility_growth",
    "SNOW": "data_software",
    "RIVN": "ev_high_beta",
    "SHOP": "ecommerce_growth",
    "INTC": "ai_semis",
    "ORCL": "enterprise_software",
    "ADBE": "enterprise_software",
    "NOW": "enterprise_software",
    "FTNT": "security_growth",
    "CRWD": "security_growth",
    "MDB": "data_software",
    "DDOG": "data_software",
    "NET": "internet_platform",
}


@dataclass(frozen=True)
class StrategyConfig:
    min_price: float = 8.0
    min_adv_usd: float = 150_000_000.0
    breakout_lookback: int = 20
    atr_lookback: int = 14
    sma_fast: int = 50
    sma_slow: int = 200
    ret_short_lookback: int = 20
    ret_medium_lookback: int = 63
    breakout_tolerance: float = 0.97
    stop_atr_mult: float = 1.2
    stop_floor_pct: float = 0.01
    target_r1_multiple: float = 1.0
    target_r2_multiple: float = 2.2
    min_signal_gates: int = 2
    max_candidates: int = 10
    max_per_complex: int = 2
    setup_name: str = "LETF_ORB_AGGRO"


@dataclass(frozen=True)
class RunArtifacts:
    asof_date: str
    output_csv: Path
    signal_ledger: Path
    selected_count: int
    evaluated_count: int
    merged_with_base: bool


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="") as handle:
            frame.to_csv(handle, index=False)
            handle.flush()
        Path(tmp_path).replace(path)
    finally:
        tmp_target = Path(tmp_path)
        if tmp_target.exists():
            tmp_target.unlink(missing_ok=True)


def _default_output_csv(repo_root: Path, asof_date: str) -> Path:
    return (
        repo_root
        / "state"
        / "strategies"
        / BOOK_ID
        / STRATEGY_ID
        / f"daily_candidates_layered_{asof_date}.csv"
    )


def _default_signal_ledger(repo_root: Path, asof_date: str) -> Path:
    return repo_root / "ledger" / "STRATEGY_SIGNALS" / STRATEGY_ID / f"{asof_date}.jsonl"


def _resolve_universe(profile: str) -> tuple[str, ...]:
    normalized = profile.strip().lower()
    if normalized not in UNIVERSE_PROFILES:
        raise ValueError(f"unsupported universe profile: {profile}")
    return UNIVERSE_PROFILES[normalized]


def _load_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"history parquet missing: {path}")
    frame = pd.read_parquet(path)
    required_columns = {"Date", "Ticker", "Open", "High", "Low", "Close", "Volume"}
    missing = required_columns - set(frame.columns)
    if missing:
        raise ValueError(f"history parquet missing required columns: {sorted(missing)}")
    frame = frame.copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    frame["Ticker"] = frame["Ticker"].astype(str).str.upper().str.strip()
    numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in numeric_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"])
    return frame.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def _true_range(series: pd.DataFrame) -> pd.Series:
    prev_close = series["Close"].shift(1)
    tr_components = pd.concat(
        [
            (series["High"] - series["Low"]).abs(),
            (series["High"] - prev_close).abs(),
            (series["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return tr_components.max(axis=1)


def _evaluate_symbol(
    symbol: str,
    symbol_frame: pd.DataFrame,
    asof_date: date,
    cfg: StrategyConfig,
) -> dict[str, Any]:
    series = symbol_frame[symbol_frame["Date"] <= pd.Timestamp(asof_date)].copy()
    series = series.sort_values("Date").reset_index(drop=True)
    min_required = max(
        cfg.sma_slow + 1,
        cfg.ret_medium_lookback + 1,
        cfg.breakout_lookback + 1,
        cfg.atr_lookback + 2,
        70,
    )
    reasons: list[str] = []
    if len(series) < min_required:
        reasons.append("insufficient_history")
        return {
            "symbol": symbol,
            "eligible": False,
            "selected": False,
            "score": None,
            "reason_codes": reasons,
            "metrics": {"history_rows": int(len(series))},
        }

    close = float(series["Close"].iloc[-1])
    sma_fast = float(series["Close"].tail(cfg.sma_fast).mean())
    sma_slow = float(series["Close"].tail(cfg.sma_slow).mean())
    high_breakout = float(series["High"].tail(cfg.breakout_lookback).max())
    ret_short = (close / float(series["Close"].iloc[-(cfg.ret_short_lookback + 1)])) - 1.0
    ret_medium = (close / float(series["Close"].iloc[-(cfg.ret_medium_lookback + 1)])) - 1.0
    tr = _true_range(series)
    atr = float(tr.tail(cfg.atr_lookback).mean())
    atr_pct = atr / close if close > 0 else 0.0
    adv20 = float((series["Close"] * series["Volume"]).tail(20).mean())
    breakout_ratio = close / high_breakout if high_breakout > 0 else 0.0

    hard_gates = {
        "price_ok": close >= cfg.min_price,
        "liquidity_ok": adv20 >= cfg.min_adv_usd,
    }
    signal_gates = {
        "trend_ok": close > sma_fast > sma_slow,
        "momentum_ok": (ret_short > 0.0 and ret_medium > 0.0),
        "breakout_ok": close >= (high_breakout * cfg.breakout_tolerance),
    }
    gates = {**hard_gates, **signal_gates}
    for gate_name, passed in hard_gates.items():
        if not passed:
            reasons.append(gate_name)
    signal_passes = int(sum(1 for passed in signal_gates.values() if passed))
    if signal_passes < cfg.min_signal_gates:
        for gate_name, passed in signal_gates.items():
            if not passed:
                reasons.append(gate_name)
        reasons.append("insufficient_signal_confluence")

    score = (ret_short * 0.45) + (ret_medium * 0.35) + (atr_pct * 0.20)
    score += max(0.0, breakout_ratio - 1.0)
    setup_pivot = max(high_breakout, close)
    stop_floor = setup_pivot * (1.0 - cfg.stop_floor_pct)
    stop_from_atr = setup_pivot - (cfg.stop_atr_mult * atr)
    stop_from_trend = sma_fast * (1.0 - cfg.stop_floor_pct)
    stop_loss = max(stop_floor, stop_from_atr, stop_from_trend)
    if stop_loss >= setup_pivot:
        stop_loss = setup_pivot * (1.0 - cfg.stop_floor_pct)
    risk = setup_pivot - stop_loss
    if risk <= 0:
        reasons.append("invalid_risk")

    entry_dist_pct = (risk / setup_pivot) * 100.0 if setup_pivot > 0 else 0.0
    if entry_dist_pct <= 0:
        reasons.append("invalid_dist_pct")
    target_r1 = setup_pivot + (risk * cfg.target_r1_multiple)
    target_r2 = setup_pivot + (risk * cfg.target_r2_multiple)

    eligible = (
        all(hard_gates.values())
        and signal_passes >= cfg.min_signal_gates
        and "invalid_risk" not in reasons
        and "invalid_dist_pct" not in reasons
    )
    return {
        "symbol": symbol,
        "eligible": eligible,
        "selected": False,
        "score": float(score),
        "reason_codes": reasons,
        "complex": COMPLEX_BY_SYMBOL.get(symbol, "other"),
        "candidate": {
            "Symbol": symbol,
            "Direction": "Long",
            "Strategy_ID": STRATEGY_ID,
            "Setup": cfg.setup_name,
            "Anchor": cfg.setup_name,
            "Entry_Level": round(setup_pivot, 4),
            "Stop_Loss": round(stop_loss, 4),
            "Target_R1": round(target_r1, 4),
            "Target_R2": round(target_r2, 4),
            "Entry_DistPct": round(entry_dist_pct, 4),
            "Price": round(close, 4),
            "Bucket": COMPLEX_BY_SYMBOL.get(symbol, "other"),
            "Score": round(score, 6),
            "Ret20": round(ret_short, 6),
            "Ret63": round(ret_medium, 6),
            "ATR14Pct": round(atr_pct, 6),
            "ADV20": round(adv20, 2),
        },
        "metrics": {
            "close": round(close, 6),
            "sma_fast": round(sma_fast, 6),
            "sma_slow": round(sma_slow, 6),
            "high_breakout": round(high_breakout, 6),
            "ret_short": round(ret_short, 6),
            "ret_medium": round(ret_medium, 6),
            "atr": round(atr, 6),
            "atr_pct": round(atr_pct, 6),
            "adv20": round(adv20, 2),
            "breakout_ratio": round(breakout_ratio, 6),
            "entry_dist_pct": round(entry_dist_pct, 6),
            "history_rows": int(len(series)),
            "signal_passes": signal_passes,
            "min_signal_gates": int(cfg.min_signal_gates),
        },
        "gates": gates,
    }


def _select_candidates(
    evaluations: list[dict[str, Any]],
    cfg: StrategyConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = [item for item in evaluations if item["eligible"]]
    eligible.sort(key=lambda item: (item["score"], item["symbol"]), reverse=True)
    selected: list[dict[str, Any]] = []
    counts_by_complex: dict[str, int] = {}
    for item in eligible:
        complex_name = str(item.get("complex", "other"))
        used = counts_by_complex.get(complex_name, 0)
        if used >= cfg.max_per_complex:
            item["reason_codes"] = list(item["reason_codes"]) + ["complex_cap_reject"]
            continue
        selected.append(item)
        item["selected"] = True
        counts_by_complex[complex_name] = used + 1
        if len(selected) >= cfg.max_candidates:
            break
    selected_candidates = [item["candidate"] for item in selected]
    return selected_candidates, evaluations


def _merge_with_base_candidates(
    base_candidates_path: Path,
    strategy_candidates: pd.DataFrame,
    evaluations: list[dict[str, Any]],
) -> pd.DataFrame:
    if not base_candidates_path.exists():
        return strategy_candidates
    base = pd.read_csv(base_candidates_path)
    if base.empty:
        return strategy_candidates
    if strategy_candidates.empty:
        return base.reset_index(drop=True)

    base_symbols = set(base["Symbol"].astype(str).str.upper()) if "Symbol" in base.columns else set()
    keep_rows: list[int] = []
    conflict_symbols: set[str] = set()
    for idx, row in strategy_candidates.iterrows():
        symbol = str(row["Symbol"]).upper()
        if symbol in base_symbols:
            conflict_symbols.add(symbol)
            continue
        keep_rows.append(idx)
    if conflict_symbols:
        for item in evaluations:
            if str(item.get("symbol")) in conflict_symbols:
                item["selected"] = False
                item["reason_codes"] = list(item["reason_codes"]) + ["symbol_conflict_with_base_candidates"]
    filtered_strategy = strategy_candidates.iloc[keep_rows].reset_index(drop=True)
    return pd.concat([base, filtered_strategy], ignore_index=True, sort=False)


def _write_signal_ledger(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [_stable_json(record) for record in sorted(records, key=lambda item: item.get("symbol", ""))]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def run_strategy(
    *,
    asof_date: str,
    repo_root: Path,
    history_path: Path | None = None,
    base_candidates_csv: Path | None = None,
    output_csv: Path | None = None,
    universe_profile: str = "aggressive_expanded",
    merge_base_candidates: bool = True,
    dry_run: bool = False,
    config: StrategyConfig | None = None,
) -> RunArtifacts:
    cfg = config or StrategyConfig()
    history_file = history_path or (repo_root / "cache" / "ohlcv_history.parquet")
    base_file = base_candidates_csv or (repo_root / "daily_candidates.csv")
    output_file = output_csv or _default_output_csv(repo_root, asof_date)
    signal_ledger = _default_signal_ledger(repo_root, asof_date)
    asof = _parse_date(asof_date)
    frame = _load_history(history_file)

    universe_symbols = _resolve_universe(universe_profile)
    universe_set = set(universe_symbols)
    filtered = frame[frame["Ticker"].isin(universe_set)].copy()
    evaluations: list[dict[str, Any]] = []
    for symbol in sorted(filtered["Ticker"].unique()):
        symbol_frame = filtered[filtered["Ticker"] == symbol]
        evaluations.append(_evaluate_symbol(symbol, symbol_frame, asof, cfg))

    selected_candidates, evaluations = _select_candidates(evaluations, cfg)
    strategy_candidates = pd.DataFrame(selected_candidates)
    if strategy_candidates.empty:
        strategy_candidates = pd.DataFrame(
            columns=[
                "Symbol",
                "Direction",
                "Strategy_ID",
                "Setup",
                "Anchor",
                "Entry_Level",
                "Stop_Loss",
                "Target_R1",
                "Target_R2",
                "Entry_DistPct",
                "Price",
                "Bucket",
                "Score",
                "Ret20",
                "Ret63",
                "ATR14Pct",
                "ADV20",
            ]
        )

    merged = strategy_candidates
    if merge_base_candidates:
        merged = _merge_with_base_candidates(base_file, strategy_candidates, evaluations)

    run_payload = {
        "strategy_id": STRATEGY_ID,
        "book_id": BOOK_ID,
        "asof_date": asof_date,
        "config": cfg.__dict__,
        "universe_profile": universe_profile,
        "universe_symbols": list(universe_symbols),
        "symbols_evaluated": sorted(filtered["Ticker"].unique().tolist()),
        "merge_base_candidates": merge_base_candidates,
        "base_candidates_csv": str(base_file),
        "history_path": str(history_file),
    }
    run_id = hashlib.sha256(_stable_json(run_payload).encode("utf-8")).hexdigest()
    signal_records = [
        {
            "record_type": "STRATEGY_SIGNAL",
            "strategy_id": STRATEGY_ID,
            "book_id": BOOK_ID,
            "asof_date": asof_date,
            "run_id": run_id,
            "symbol": item.get("symbol"),
            "complex": item.get("complex"),
            "eligible": bool(item.get("eligible")),
            "selected": bool(item.get("selected")),
            "score": item.get("score"),
            "reason_codes": list(item.get("reason_codes", [])),
            "gates": item.get("gates", {}),
            "metrics": item.get("metrics", {}),
            "candidate": item.get("candidate"),
        }
        for item in evaluations
    ]

    if not dry_run:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        signal_ledger.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_csv(output_file, merged)
        _write_signal_ledger(signal_ledger, signal_records)

    return RunArtifacts(
        asof_date=asof_date,
        output_csv=output_file,
        signal_ledger=signal_ledger,
        selected_count=int(sum(1 for item in evaluations if item.get("selected"))),
        evaluated_count=int(len(evaluations)),
        merged_with_base=merge_base_candidates,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build auditable layered candidates for S2_LETF_ORB_AGGRO.",
    )
    parser.add_argument("--asof", required=True, help="As-of date (YYYY-MM-DD)")
    parser.add_argument(
        "--history-path",
        default="cache/ohlcv_history.parquet",
        help="Path to OHLCV parquet (offline source).",
    )
    parser.add_argument(
        "--base-candidates-csv",
        default="daily_candidates.csv",
        help="Base AVWAP candidates CSV to merge with.",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Destination candidates CSV. Default is strategy state path.",
    )
    parser.add_argument(
        "--universe-profile",
        default="aggressive_expanded",
        choices=sorted(UNIVERSE_PROFILES.keys()),
        help="Universe profile used for signal generation.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=StrategyConfig().max_candidates,
        help="Maximum LETF candidates to add.",
    )
    parser.add_argument(
        "--max-per-complex",
        type=int,
        default=StrategyConfig().max_per_complex,
        help="Maximum selected symbols per complex bucket.",
    )
    parser.add_argument("--min-price", type=float, default=StrategyConfig().min_price)
    parser.add_argument("--min-adv-usd", type=float, default=StrategyConfig().min_adv_usd)
    parser.add_argument("--breakout-lookback", type=int, default=StrategyConfig().breakout_lookback)
    parser.add_argument("--atr-lookback", type=int, default=StrategyConfig().atr_lookback)
    parser.add_argument("--sma-fast", type=int, default=StrategyConfig().sma_fast)
    parser.add_argument("--sma-slow", type=int, default=StrategyConfig().sma_slow)
    parser.add_argument("--ret-short-lookback", type=int, default=StrategyConfig().ret_short_lookback)
    parser.add_argument("--ret-medium-lookback", type=int, default=StrategyConfig().ret_medium_lookback)
    parser.add_argument("--breakout-tolerance", type=float, default=StrategyConfig().breakout_tolerance)
    parser.add_argument("--stop-atr-mult", type=float, default=StrategyConfig().stop_atr_mult)
    parser.add_argument("--target-r1-multiple", type=float, default=StrategyConfig().target_r1_multiple)
    parser.add_argument("--target-r2-multiple", type=float, default=StrategyConfig().target_r2_multiple)
    parser.add_argument("--min-signal-gates", type=int, default=StrategyConfig().min_signal_gates)
    parser.add_argument(
        "--no-merge-base",
        action="store_true",
        default=False,
        help="If set, output strategy-only candidates.",
    )
    parser.add_argument("--dry-run", action="store_true", default=False, help="Do not write output artifacts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    cfg = StrategyConfig(
        min_price=max(0.01, float(args.min_price)),
        min_adv_usd=max(0.0, float(args.min_adv_usd)),
        breakout_lookback=max(2, int(args.breakout_lookback)),
        atr_lookback=max(2, int(args.atr_lookback)),
        sma_fast=max(2, int(args.sma_fast)),
        sma_slow=max(2, int(args.sma_slow)),
        ret_short_lookback=max(1, int(args.ret_short_lookback)),
        ret_medium_lookback=max(2, int(args.ret_medium_lookback)),
        breakout_tolerance=min(1.0, max(0.5, float(args.breakout_tolerance))),
        stop_atr_mult=max(0.1, float(args.stop_atr_mult)),
        target_r1_multiple=max(0.1, float(args.target_r1_multiple)),
        target_r2_multiple=max(0.2, float(args.target_r2_multiple)),
        min_signal_gates=min(3, max(1, int(args.min_signal_gates))),
        max_candidates=max(1, int(args.max_candidates)),
        max_per_complex=max(1, int(args.max_per_complex)),
    )
    if cfg.sma_fast > cfg.sma_slow:
        cfg = StrategyConfig(
            **{
                **cfg.__dict__,
                "sma_fast": cfg.sma_slow,
            }
        )
    if cfg.ret_short_lookback >= cfg.ret_medium_lookback:
        cfg = StrategyConfig(
            **{
                **cfg.__dict__,
                "ret_short_lookback": max(1, cfg.ret_medium_lookback - 1),
            }
        )
    output_csv = Path(args.output_csv).resolve() if args.output_csv else None
    result = run_strategy(
        asof_date=args.asof,
        repo_root=repo_root,
        history_path=Path(args.history_path),
        base_candidates_csv=Path(args.base_candidates_csv),
        output_csv=output_csv,
        universe_profile=args.universe_profile,
        merge_base_candidates=not args.no_merge_base,
        dry_run=args.dry_run,
        config=cfg,
    )
    print(
        "S2_LETF_ORB_AGGRO: "
        f"asof={result.asof_date} "
        f"evaluated={result.evaluated_count} "
        f"selected={result.selected_count} "
        f"universe_profile={args.universe_profile} "
        f"merged_with_base={int(result.merged_with_base)} "
        f"output_csv={result.output_csv} "
        f"signal_ledger={result.signal_ledger} "
        f"dry_run={int(args.dry_run)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
