from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")

from execution_v2 import buy_loop
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID, StrategyID


class _FakeStore:
    def __init__(self) -> None:
        self.candidates: dict[str, dict] = {}
        self.entry_intents: dict[str, object] = {}

    def upsert_candidate(
        self, *, symbol: str, first_seen_ts: float, expires_ts: float, pivot_level: float, notes: str
    ) -> None:
        self.candidates[symbol] = {
            "first_seen_ts": first_seen_ts,
            "expires_ts": expires_ts,
            "pivot_level": pivot_level,
            "notes": notes,
        }

    def list_active_candidates(self, now_ts: float) -> list[str]:
        return list(self.candidates.keys())

    def get_entry_intent(self, symbol: str):
        return self.entry_intents.get(symbol)

    def put_entry_intent(self, intent) -> None:
        self.entry_intents[intent.symbol] = intent

    def list_positions(self):
        return []


class _FakeMarketData:
    def get_last_two_closed_10m(self, symbol: str):
        return [SimpleNamespace(close=100.0), SimpleNamespace(close=100.0)]

    def get_daily_bars(self, symbol: str):
        return []


def _write_candidates_csv(path, *, strategy_id: str | None = None) -> None:
    fieldnames = [
        "Symbol",
        "Entry_Level",
        "Stop_Loss",
        "Target_R1",
        "Target_R2",
        "Entry_DistPct",
        "Price",
    ]
    if strategy_id is not None:
        fieldnames.append("Strategy_ID")

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        row = {
            "Symbol": "AAA",
            "Entry_Level": 100.0,
            "Stop_Loss": 95.0,
            "Target_R1": 105.0,
            "Target_R2": 110.0,
            "Entry_DistPct": 2.0,
            "Price": 100.0,
        }
        if strategy_id is not None:
            row["Strategy_ID"] = strategy_id
        writer.writerow(row)


def test_load_candidates_defaults_to_avwap_strategy_id(tmp_path) -> None:
    csv_path = tmp_path / "candidates_default.csv"
    _write_candidates_csv(csv_path, strategy_id=None)

    candidates = buy_loop.load_candidates(str(csv_path))

    assert len(candidates) == 1
    assert candidates[0].strategy_id == DEFAULT_STRATEGY_ID


def test_load_candidates_uses_strategy_id_from_csv(tmp_path) -> None:
    csv_path = tmp_path / "candidates_custom.csv"
    _write_candidates_csv(csv_path, strategy_id=StrategyID.S2_LETF_ORB_AGGRO.value)

    candidates = buy_loop.load_candidates(str(csv_path))

    assert len(candidates) == 1
    assert candidates[0].strategy_id == StrategyID.S2_LETF_ORB_AGGRO.value


def test_evaluate_and_create_entry_intents_propagates_strategy_id(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_path = tmp_path / "candidates_custom.csv"
    _write_candidates_csv(csv_path, strategy_id=StrategyID.S2_LETF_ORB_AGGRO.value)
    cfg = buy_loop.BuyLoopConfig(
        candidates_csv=str(csv_path),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
    )
    store = _FakeStore()
    md = _FakeMarketData()

    monkeypatch.setattr(
        buy_loop,
        "boh_confirmed_option2",
        lambda *_: SimpleNamespace(confirmed=True, confirm_bar_ts=None),
    )
    monkeypatch.setattr(buy_loop, "compute_size_shares", lambda **_: 5)
    monkeypatch.setattr(buy_loop.exits, "compute_stop_price", lambda *args, **kwargs: 95.0)
    monkeypatch.setattr(buy_loop.exits, "validate_risk", lambda *_: True)

    created = buy_loop.evaluate_and_create_entry_intents(store, md, cfg, account_equity=100_000.0)

    assert created == 1
    intent = store.entry_intents["AAA"]
    assert intent.strategy_id == StrategyID.S2_LETF_ORB_AGGRO.value
