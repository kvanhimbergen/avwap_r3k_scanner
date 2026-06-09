"""Tests for ShadowBook persistence: save/load round-trip + continuation."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from strategies.raec_v6.shadow_book import ShadowBook


def _build_book(tmp_path: Path) -> ShadowBook:
    book = ShadowBook(starting_cash=230_000)
    asof = date(2026, 6, 1)
    for i in range(5):
        book.step(
            asof=asof + timedelta(days=i),
            target_weights={"SPY": 0.6, "BIL": 0.4},
            close_prices={"SPY": 600 + i, "BIL": 90},
        )
    return book


def test_save_load_roundtrip(tmp_path: Path) -> None:
    book = _build_book(tmp_path)
    p = tmp_path / "shadow.json"
    book.save(p)
    assert p.exists()
    loaded = ShadowBook.load(p)
    assert loaded.equity == book.equity
    assert loaded.cash == book.cash
    assert loaded.positions == book.positions
    assert loaded.equity_curve == book.equity_curve
    assert loaded.cash_curve == book.cash_curve
    assert loaded.daily_returns == book.daily_returns
    assert loaded.asof_history == book.asof_history
    assert len(loaded.trade_log) == len(book.trade_log)


def test_loaded_book_continues_stepping(tmp_path: Path) -> None:
    book = _build_book(tmp_path)
    p = tmp_path / "shadow.json"
    book.save(p)
    loaded = ShadowBook.load(p)

    # Continue with one more day
    next_asof = book.asof_history[-1] + timedelta(days=1)
    result = loaded.step(
        asof=next_asof,
        target_weights={"SPY": 0.5, "BIL": 0.5},
        close_prices={"SPY": 610, "BIL": 90},
    )
    assert result.equity > 0
    assert len(loaded.equity_curve) == len(book.equity_curve) + 1
    assert len(loaded.trade_log) > len(book.trade_log)


def test_save_is_atomic(tmp_path: Path) -> None:
    """Save uses a tmp file then rename — no partial writes."""
    book = _build_book(tmp_path)
    p = tmp_path / "shadow.json"
    book.save(p)
    # No leftover .tmp file
    assert not (p.with_suffix(p.suffix + ".tmp")).exists()
    # Loadable JSON
    data = json.loads(p.read_text())
    assert "schema_version" in data
    assert data["schema_version"] == ShadowBook.SCHEMA_VERSION


def test_load_rejects_unknown_schema_version(tmp_path: Path) -> None:
    """A schema mismatch must NOT silently coerce — it has to error."""
    p = tmp_path / "shadow.json"
    p.write_text(json.dumps({"schema_version": 999, "starting_cash": 100_000}))
    with pytest.raises(ValueError, match="schema version"):
        ShadowBook.load(p)


def test_empty_book_save_load(tmp_path: Path) -> None:
    """A freshly-constructed book with no steps can still be saved + loaded."""
    book = ShadowBook(starting_cash=230_000)
    p = tmp_path / "shadow.json"
    book.save(p)
    loaded = ShadowBook.load(p)
    assert loaded.starting_cash == 230_000
    assert loaded.equity_curve == []
    assert loaded.positions == {}
