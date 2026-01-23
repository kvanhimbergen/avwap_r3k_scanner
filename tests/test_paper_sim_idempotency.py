from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from execution_v2 import paper_sim


def test_paper_sim_idempotency(tmp_path) -> None:
    intent = SimpleNamespace(symbol="AAA", size_shares=10, entry_price=123.45)
    now_utc = datetime(2024, 1, 2, tzinfo=timezone.utc)
    date_ny = "2024-01-02"

    fills_first = paper_sim.simulate_fills(
        [intent],
        date_ny=date_ny,
        now_utc=now_utc,
        repo_root=tmp_path,
    )
    fills_second = paper_sim.simulate_fills(
        [intent],
        date_ny=date_ny,
        now_utc=now_utc,
        repo_root=tmp_path,
    )

    ledger_path = tmp_path / "ledger" / "PAPER_SIM" / f"{date_ny}.jsonl"
    ledger_lines = ledger_path.read_text().strip().splitlines()

    assert len(fills_first) == 1
    assert fills_second == []
    assert len(ledger_lines) == 1
