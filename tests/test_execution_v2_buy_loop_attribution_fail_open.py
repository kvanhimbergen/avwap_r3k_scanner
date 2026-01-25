from __future__ import annotations

import csv
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")

from execution_v2 import buy_loop
from portfolio.risk_controls import RiskControlResult, RiskControls


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


class _FakeMarketData:
    def get_last_two_closed_10m(self, symbol: str):
        return [SimpleNamespace(close=100.0), SimpleNamespace(close=100.0)]

    def get_daily_bars(self, symbol: str):
        return []


def _write_candidates_csv(path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Symbol", "Entry_Level", "Stop_Loss", "Target_R2", "Entry_DistPct", "Price"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Symbol": "AAA",
                "Entry_Level": 100.0,
                "Stop_Loss": 95.0,
                "Target_R2": 110.0,
                "Entry_DistPct": 0.5,
                "Price": 100.0,
            }
        )


def test_attribution_import_failure_is_fail_open(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "candidates.csv"
    _write_candidates_csv(csv_path)

    cfg = buy_loop.BuyLoopConfig(candidates_csv=str(csv_path), entry_delay_min_sec=0, entry_delay_max_sec=0)
    store = _FakeStore()
    md = _FakeMarketData()

    controls = RiskControls(
        risk_multiplier=1.0,
        max_gross_exposure=None,
        max_positions=None,
        per_position_cap=None,
        throttle_reason="ok",
    )
    rc_result = RiskControlResult(
        controls=controls,
        record=None,
        reasons=[],
        throttle=None,
        source=None,
        resolved_ny_date="2024-01-02",
    )

    monkeypatch.setenv("E2_REGIME_RISK_MODULATION", "1")
    monkeypatch.setenv("E3_RISK_ATTRIBUTION_WRITE", "1")
    monkeypatch.setattr(buy_loop, "risk_modulation_enabled", lambda: True)
    monkeypatch.setattr(buy_loop, "resolve_drawdown_guardrail", lambda **_: (0.0, 0.2, []))
    monkeypatch.setattr(buy_loop, "build_risk_controls", lambda **_: rc_result)
    monkeypatch.setattr(buy_loop, "boh_confirmed_option2", lambda *_: SimpleNamespace(confirmed=True, confirm_bar_ts=None))
    monkeypatch.setattr(buy_loop, "compute_size_shares", lambda **_: 10)
    monkeypatch.setattr(buy_loop, "adjust_order_quantity", lambda **_: 10)
    monkeypatch.setattr(buy_loop.exits, "compute_stop_price", lambda *args, **kwargs: 95.0)
    monkeypatch.setattr(buy_loop.exits, "validate_risk", lambda *_: True)
    monkeypatch.setattr(buy_loop.importlib, "import_module", lambda *_: (_ for _ in ()).throw(ImportError("boom")))

    created = buy_loop.evaluate_and_create_entry_intents(store, md, cfg, account_equity=100_000.0)

    assert created == 1
    assert "AAA" in store.entry_intents
    output = capsys.readouterr().out
    assert "WARN: risk attribution import failed" in output
