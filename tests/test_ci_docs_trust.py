from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

import backtest_engine
import scan_engine
from config import cfg
from provenance import REQUIRED_PROVENANCE_FIELDS, compute_run_id


def _make_history_frame(symbols: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for sym_idx, symbol in enumerate(symbols):
        base = 50.0 + sym_idx * 10.0
        for idx, dt in enumerate(dates):
            close_px = base + idx * 0.5
            open_px = close_px - 0.2
            high_px = close_px + 0.6
            low_px = close_px - 0.6
            rows.append(
                {
                    "Date": dt,
                    "Ticker": symbol,
                    "Open": open_px,
                    "High": high_px,
                    "Low": low_px,
                    "Close": close_px,
                    "Volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def test_required_docs_exist() -> None:
    trust_doc = Path("docs/backtests_trust.md")
    invalidation_doc = Path("docs/backtests_invalidation.md")
    assert trust_doc.exists()
    assert invalidation_doc.exists()


def test_summary_includes_required_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    history = _make_history_frame(["AAA", "BBB"], dates)
    history_path = tmp_path / "ohlcv_history.parquet"
    history.to_parquet(history_path, index=False)

    monkeypatch.setattr(scan_engine, "build_candidate_row", lambda *args, **kwargs: None)
    monkeypatch.setattr(cfg, "BACKTEST_OHLCV_PATH", str(history_path))
    monkeypatch.setattr(cfg, "BACKTEST_OUTPUT_DIR", str(tmp_path / "out"))

    backtest_engine.run_backtest(
        cfg,
        dates[0].date(),
        dates[-1].date(),
        universe_symbols=["AAA", "BBB"],
    )

    summary_path = tmp_path / "out" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    for key in REQUIRED_PROVENANCE_FIELDS:
        assert key in summary
        assert summary[key] not in (None, "")


def test_run_id_stable_for_identical_inputs() -> None:
    params = {"start_date": "2024-01-01", "end_date": "2024-02-01"}
    run_id_a = compute_run_id("abc123", "cfg456", "data789", "single", params)
    run_id_b = compute_run_id("abc123", "cfg456", "data789", "single", params)
    assert run_id_a == run_id_b


def test_run_tests_entrypoint_covers_all_tests() -> None:
    tests_root = Path("tests")
    run_tests_path = tests_root / "run_tests.py"
    content = run_tests_path.read_text(encoding="utf-8")
    declared = set(re.findall(r"test_[a-zA-Z0-9_]+\.py", content))
    expected = {path.name for path in tests_root.glob("test_*.py")}
    assert declared == expected
