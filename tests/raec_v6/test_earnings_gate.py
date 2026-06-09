"""Tests for the earnings gate."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from strategies.raec_v6.signals.earnings_gate import (
    _load_live_cache,
    names_near_earnings_backtest,
    names_near_earnings_live,
)


def test_live_gate_flags_only_value_true(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({
        "NVDA": {"value": False, "asof": "2026-06-09"},
        "ADBE": {"value": True, "asof": "2026-06-09"},
        "MSFT": {"value": False, "asof": "2026-06-09"},
    }))
    # lru_cache clear (the loader caches by path; different path is fine)
    flagged = names_near_earnings_live(
        ["NVDA", "ADBE", "MSFT"],
        cache_path=cache_path,
    )
    assert flagged == {"ADBE"}


def test_live_gate_missing_cache_returns_empty(tmp_path: Path) -> None:
    """No cache file → no symbols are flagged (safe default)."""
    flagged = names_near_earnings_live(
        ["NVDA", "ADBE"],
        cache_path=tmp_path / "missing.json",
    )
    assert flagged == set()


def test_live_gate_unknown_symbol_not_flagged(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"NVDA": {"value": True}}))
    flagged = names_near_earnings_live(
        ["FOO_NOT_IN_CACHE"],
        cache_path=cache_path,
    )
    assert flagged == set()


def test_live_gate_case_insensitive(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"NVDA": {"value": True}}))
    flagged = names_near_earnings_live(
        ["nvda"],
        cache_path=cache_path,
    )
    assert flagged == {"NVDA"}


def test_backtest_gate_empty_calendar_returns_empty(tmp_path: Path) -> None:
    """When the PIT calendar parquet is empty/missing, gate is disabled."""
    flagged = names_near_earnings_backtest(
        ["NVDA", "ADBE", "MSFT"],
        asof=date(2024, 11, 15),
    )
    assert flagged == set()
