from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from execution_v2 import paper_sim


def _write_candidates(tmp_path, rows: list[dict]) -> None:
    csv_path = tmp_path / "daily_candidates.csv"
    headers = list(rows[0].keys())
    csv_path.write_text(
        ",".join(headers) + "\n" + "\n".join(
            ",".join(str(row[h]) for h in headers) for row in rows
        )
    )


def test_entry_price_overrides_csv(tmp_path) -> None:
    _write_candidates(
        tmp_path,
        [
            {
                "ScanDate": "2024-01-02",
                "Symbol": "AAA",
                "Entry_Level": 99.0,
            }
        ],
    )
    intent = SimpleNamespace(symbol="AAA", size_shares=5, entry_price=123.45)
    fills = paper_sim.simulate_fills(
        [intent],
        date_ny="2024-01-02",
        now_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        repo_root=tmp_path,
    )

    assert fills[0]["price"] == pytest.approx(123.45)
    assert fills[0]["source"] == "intent_entry_price"


def test_csv_entry_level_used_when_no_intent_price(tmp_path) -> None:
    _write_candidates(
        tmp_path,
        [
            {
                "ScanDate": "2024-01-02",
                "Symbol": "BBB",
                "Entry_Level": 55.5,
            }
        ],
    )
    intent = SimpleNamespace(symbol="BBB", size_shares=3)
    fills = paper_sim.simulate_fills(
        [intent],
        date_ny="2024-01-02",
        now_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        repo_root=tmp_path,
    )

    assert fills[0]["price"] == pytest.approx(55.5)
    assert fills[0]["source"] == "daily_candidates_entry_level"


def test_fallback_used_when_symbol_absent(monkeypatch, tmp_path) -> None:
    _write_candidates(
        tmp_path,
        [
            {
                "ScanDate": "2024-01-02",
                "Symbol": "CCC",
                "Entry_Level": 10.0,
            }
        ],
    )

    monkeypatch.setattr(paper_sim, "_latest_close_from_cache", lambda *_args, **_kwargs: 77.7)
    intent = SimpleNamespace(symbol="DDD", size_shares=2)
    fills = paper_sim.simulate_fills(
        [intent],
        date_ny="2024-01-02",
        now_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        repo_root=tmp_path,
    )

    assert fills[0]["price"] == pytest.approx(77.7)
    assert fills[0]["source"] == "latest_close_cache"
