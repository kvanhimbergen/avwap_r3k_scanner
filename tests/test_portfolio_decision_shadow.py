from __future__ import annotations

import json
from pathlib import Path

from analytics.portfolio_decision import (
    DEFAULT_CONFIG,
    PortfolioDecisionConfig,
    build_portfolio_decisions,
    dumps_portfolio_decision_batch,
    load_daily_candidates,
)
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID


def _write_candidates(path: Path, symbols: list[str]) -> None:
    rows = ["symbol"] + symbols
    path.write_text("\n".join(rows), encoding="utf-8")


def _write_snapshot(path: Path, *, date_ny: str, capital: float, drawdown: float, positions: list[dict]) -> None:
    payload_positions = []
    for position in positions:
        item = dict(position)
        item.setdefault("strategy_id", DEFAULT_STRATEGY_ID)
        payload_positions.append(item)
    payload = {
        "schema_version": 2,
        "date_ny": date_ny,
        "run_id": "test",
        "strategy_ids": [DEFAULT_STRATEGY_ID],
        "capital": {"starting": capital, "ending": capital},
        "gross_exposure": 0.0,
        "net_exposure": 0.0,
        "positions": payload_positions,
        "pnl": {},
        "metrics": {"drawdown": drawdown},
        "provenance": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_new_entries(path: Path, count: int) -> None:
    path.write_text(json.dumps({"new_entries": count}), encoding="utf-8")


def test_deterministic_output_and_ordering(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["MSFT", "AAPL"])
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.0,
        positions=[
            {"symbol": "AAPL", "qty": 10, "avg_price": 100.0, "mark_price": 110.0, "notional": 1100},
        ],
    )
    _write_new_entries(new_entries, 0)

    config = PortfolioDecisionConfig(
        max_open_positions=10,
        max_new_entries_per_day=5,
        max_symbol_concentration_pct=0.5,
        max_gross_exposure_pct=1.0,
        max_drawdown_pct_block=0.5,
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=str(new_entries),
        config=config,
    )

    payload_first = dumps_portfolio_decision_batch(batch)
    payload_second = dumps_portfolio_decision_batch(batch)

    assert payload_first == payload_second
    assert [decision.symbol for decision in batch.decisions] == ["AAPL", "MSFT"]


def test_missing_candidates_returns_reason_code(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.csv"
    symbols, reason_codes = load_daily_candidates(str(missing_path))
    assert symbols == []
    assert reason_codes == ["CANDIDATES_MISSING"]


def test_missing_portfolio_snapshot_blocks(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["AAPL"])
    _write_new_entries(new_entries, 0)

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(tmp_path / "missing_snapshot.json"),
        new_entries_path=str(new_entries),
        config=DEFAULT_CONFIG,
    )

    assert batch.decisions[0].decision == "BLOCK"
    assert batch.decisions[0].reason_codes == ["PORTFOLIO_SNAPSHOT_MISSING"]


def test_missing_new_entries_blocks(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"

    _write_candidates(candidates, ["AAPL"])
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.0,
        positions=[
            {"symbol": "AAPL", "qty": 10, "avg_price": 100.0, "mark_price": 110.0, "notional": 1100},
        ],
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=None,
        config=DEFAULT_CONFIG,
    )

    assert batch.decisions[0].decision == "BLOCK"
    assert batch.decisions[0].reason_codes == ["OPEN_POSITIONS_MISSING"]


def test_guardrail_max_open_positions(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["AAPL"])
    _write_new_entries(new_entries, 0)
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.0,
        positions=[
            {"symbol": "AAPL", "qty": 10, "avg_price": 100.0, "mark_price": 110.0, "notional": 1100},
            {"symbol": "MSFT", "qty": 5, "avg_price": 200.0, "mark_price": 210.0, "notional": 1050},
        ],
    )

    config = PortfolioDecisionConfig(
        max_open_positions=1,
        max_new_entries_per_day=5,
        max_symbol_concentration_pct=2.0,
        max_gross_exposure_pct=1.0,
        max_drawdown_pct_block=0.5,
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=str(new_entries),
        config=config,
    )

    assert batch.decisions[0].reason_codes == ["LIMIT_MAX_OPEN_POSITIONS"]


def test_guardrail_symbol_concentration(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["AAPL", "MSFT"])
    _write_new_entries(new_entries, 0)
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.0,
        positions=[
            {"symbol": "AAPL", "qty": 400, "avg_price": 100.0, "mark_price": 110.0, "notional": 44000},
            {"symbol": "MSFT", "qty": 10, "avg_price": 50.0, "mark_price": 55.0, "notional": 550},
        ],
    )

    config = PortfolioDecisionConfig(
        max_open_positions=10,
        max_new_entries_per_day=5,
        max_symbol_concentration_pct=0.3,
        max_gross_exposure_pct=1.0,
        max_drawdown_pct_block=0.5,
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=str(new_entries),
        config=config,
    )

    decisions = {decision.symbol: decision for decision in batch.decisions}
    assert decisions["AAPL"].reason_codes == ["LIMIT_SYMBOL_CONCENTRATION"]
    assert decisions["MSFT"].reason_codes == ["ALLOW_WITHIN_LIMITS"]


def test_guardrail_gross_exposure(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["AAPL"])
    _write_new_entries(new_entries, 0)
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.0,
        positions=[
            {"symbol": "AAPL", "qty": 1000, "avg_price": 120.0, "mark_price": 125.0, "notional": 125000},
        ],
    )

    config = PortfolioDecisionConfig(
        max_open_positions=10,
        max_new_entries_per_day=5,
        max_symbol_concentration_pct=2.0,
        max_gross_exposure_pct=0.5,
        max_drawdown_pct_block=0.5,
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=str(new_entries),
        config=config,
    )

    assert batch.decisions[0].reason_codes == ["LIMIT_GROSS_EXPOSURE"]


def test_guardrail_drawdown_throttle(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["AAPL"])
    _write_new_entries(new_entries, 0)
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.3,
        positions=[
            {"symbol": "AAPL", "qty": 10, "avg_price": 100.0, "mark_price": 110.0, "notional": 1100},
        ],
    )

    config = PortfolioDecisionConfig(
        max_open_positions=10,
        max_new_entries_per_day=5,
        max_symbol_concentration_pct=2.0,
        max_gross_exposure_pct=1.0,
        max_drawdown_pct_block=0.2,
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=str(new_entries),
        config=config,
    )

    assert batch.decisions[0].reason_codes == ["LIMIT_DRAWDOWN_THROTTLE"]


def test_guardrail_max_new_entries_per_day(tmp_path: Path) -> None:
    candidates = tmp_path / "daily_candidates.csv"
    snapshot = tmp_path / "snapshot.json"
    new_entries = tmp_path / "new_entries.json"

    _write_candidates(candidates, ["AAPL"])
    _write_new_entries(new_entries, 5)
    _write_snapshot(
        snapshot,
        date_ny="2024-01-02",
        capital=100000.0,
        drawdown=0.0,
        positions=[
            {"symbol": "AAPL", "qty": 10, "avg_price": 100.0, "mark_price": 110.0, "notional": 1100},
        ],
    )

    config = PortfolioDecisionConfig(
        max_open_positions=10,
        max_new_entries_per_day=5,
        max_symbol_concentration_pct=2.0,
        max_gross_exposure_pct=1.0,
        max_drawdown_pct_block=0.5,
    )

    batch = build_portfolio_decisions(
        date_ny="2024-01-02",
        candidates_path=str(candidates),
        snapshot_path=str(snapshot),
        new_entries_path=str(new_entries),
        config=config,
    )

    assert batch.decisions[0].reason_codes == ["LIMIT_MAX_NEW_ENTRIES_PER_DAY"]
