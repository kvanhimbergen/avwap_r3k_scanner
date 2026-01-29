from __future__ import annotations

from datetime import datetime, timezone

from execution_v2 import buy_loop
from execution_v2.boh import Bar10m
from execution_v2.entry_suppression import OneShotConfig, evaluate_one_shot
from execution_v2.state_store import StateStore


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += seconds


class FakeMarketData:
    def __init__(self, bar_sets: list[list[Bar10m]], daily_bars: list[dict]) -> None:
        self._bar_sets = bar_sets
        self._daily_bars = daily_bars
        self.calls = 0

    def get_last_two_closed_10m(self, symbol: str) -> list[Bar10m]:
        idx = min(self.calls, len(self._bar_sets) - 1)
        self.calls += 1
        return self._bar_sets[idx]

    def get_daily_bars(self, symbol: str) -> list[dict]:
        return self._daily_bars


def _write_candidates(path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "Symbol,Entry_Level,Stop_Loss,Target_R2,Entry_DistPct,Price\n"
            "AAPL,100,95,110,1.0,100\n"
        )


def _daily_bars_for_entry() -> list[dict]:
    ts = datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp()
    return [
        {"ts": ts, "open": 101, "high": 102, "low": 99, "close": 101},
        {"ts": ts + 86400, "open": 100, "high": 101, "low": 98, "close": 100},
        {"ts": ts + 2 * 86400, "open": 100, "high": 101, "low": 99, "close": 100},
    ]


def test_edge_window_rechecks_confirm_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAX_RISK_PER_SHARE_DOLLARS", "100.0")
    monkeypatch.setenv("STOP_BUFFER_DOLLARS", "0.0")

    db_path = tmp_path / "state.sqlite"
    store = StateStore(str(db_path))
    candidates_path = tmp_path / "candidates.csv"
    _write_candidates(str(candidates_path))

    pivot = 100.0
    bar_sets = [
        [
            Bar10m(ts=1, open=99.5, high=100.1, low=99.0, close=99.7),
            Bar10m(ts=2, open=99.7, high=100.0, low=99.4, close=99.9),
        ],
        [
            Bar10m(ts=3, open=99.8, high=100.1, low=99.6, close=99.95),
            Bar10m(ts=4, open=99.9, high=100.0, low=99.7, close=99.98),
        ],
        [
            Bar10m(ts=5, open=100.1, high=100.5, low=100.0, close=100.3),
            Bar10m(ts=6, open=100.2, high=100.4, low=100.1, close=100.2),
        ],
    ]
    md = FakeMarketData(bar_sets=bar_sets, daily_bars=_daily_bars_for_entry())
    cfg = buy_loop.BuyLoopConfig(candidates_csv=str(candidates_path))
    edge_cfg = buy_loop.EdgeWindowConfig(enabled=True, rechecks=3, delay_sec=5.0, proximity_pct=0.002)
    edge_report = buy_loop.EdgeWindowReport()
    fake_clock = FakeClock()

    created = buy_loop.evaluate_and_create_entry_intents(
        store,
        md,
        cfg,
        account_equity=100000,
        created_intents=[],
        edge_window=edge_cfg,
        edge_report=edge_report,
        edge_clock=buy_loop.EdgeWindowClock(now=fake_clock.now, sleep=fake_clock.sleep),
    )

    assert created == 1
    assert edge_report.engaged_symbols == ["AAPL"]
    assert edge_report.rechecks_attempted == 2
    assert edge_report.confirmed_symbols == ["AAPL"]
    assert fake_clock.now() == 10.0
    assert store.get_entry_intent("AAPL") is not None


def test_edge_window_disabled_defaults_no_recheck(tmp_path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = StateStore(str(db_path))
    candidates_path = tmp_path / "candidates.csv"
    _write_candidates(str(candidates_path))

    bar_sets = [
        [
            Bar10m(ts=1, open=100.1, high=100.5, low=100.0, close=100.2),
            Bar10m(ts=2, open=100.2, high=100.4, low=100.1, close=100.3),
        ]
    ]
    md = FakeMarketData(bar_sets=bar_sets, daily_bars=_daily_bars_for_entry())
    cfg = buy_loop.BuyLoopConfig(candidates_csv=str(candidates_path))
    edge_report = buy_loop.EdgeWindowReport()

    created = buy_loop.evaluate_and_create_entry_intents(
        store,
        md,
        cfg,
        account_equity=100000,
        created_intents=[],
        edge_window=buy_loop.EdgeWindowConfig(enabled=False),
        edge_report=edge_report,
    )

    assert created == 1
    assert edge_report.rechecks_attempted == 0


def test_one_shot_cooldown_persists_across_restart(tmp_path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = StateStore(str(db_path))
    store.record_entry_fill(
        date_ny="2024-01-02",
        strategy_id="s1",
        symbol="AAPL",
        filled_ts=0.0,
        source="paper_sim",
    )

    config = OneShotConfig(enabled=True, reset_mode="cooldown", cooldown_minutes=60)
    decision = evaluate_one_shot(
        store=store,
        date_ny="2024-01-02",
        strategy_id="s1",
        symbol="AAPL",
        now_ts=30 * 60,
        config=config,
    )
    assert decision.blocked is True

    store = StateStore(str(db_path))
    decision = evaluate_one_shot(
        store=store,
        date_ny="2024-01-02",
        strategy_id="s1",
        symbol="AAPL",
        now_ts=61 * 60,
        config=config,
    )
    assert decision.blocked is False
