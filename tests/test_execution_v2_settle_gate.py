import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import clocks
from execution_v2 import execution_main


class _DummyStore:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def list_positions(self):
        return []

    def pop_trim_intents(self):
        return []


def _read_latest_decision(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_settle_gate_blocks_dry_run_entries(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text("symbol\n", encoding="utf-8")
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("MARKET_SETTLE_MINUTES", "5")
    monkeypatch.chdir(tmp_path)

    now_et = datetime(2024, 1, 2, 9, 32, tzinfo=clocks.ET)
    monkeypatch.setattr(
        execution_main.clocks,
        "now_snapshot",
        lambda: SimpleNamespace(market_open=True, now_et=now_et),
    )
    monkeypatch.setattr(execution_main, "StateStore", _DummyStore)
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)

    called = {"buy_loop": False}

    def _raise_if_called(*_args, **_kwargs):
        called["buy_loop"] = True
        raise AssertionError("buy_loop should not be called during settle delay")

    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", _raise_if_called)

    cfg = SimpleNamespace(
        candidates_csv=str(candidates_path),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(tmp_path / "execution.sqlite"),
        execution_mode="DRY_RUN",
        dry_run=True,
        poll_seconds=300,
        ignore_market_hours=False,
    )

    execution_main.run_once(cfg)

    heartbeat_path = state_dir / "execution_heartbeat.json"
    assert heartbeat_path.exists()
    latest_path = state_dir / "portfolio_decision_latest.json"
    assert latest_path.exists()
    decision = _read_latest_decision(latest_path)
    block_codes = {block["code"] for block in decision["gates"]["blocks"]}
    assert "market_settle_delay" in block_codes
    assert called["buy_loop"] is False


def test_settle_gate_allows_exits_alpaca_paper(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text("symbol\n", encoding="utf-8")
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("MARKET_SETTLE_MINUTES", "5")
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("APCA_API_BASE_URL", execution_main.PAPER_BASE_URL)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_main, "StateStore", _DummyStore)

    now_et = datetime(2024, 1, 2, 9, 32, tzinfo=clocks.ET)

    class _DummyClock:
        is_open = True
        timestamp = now_et.astimezone(timezone.utc)
        next_open = None
        next_close = None

    class _DummyTradingClient:
        def get_clock(self):
            return _DummyClock()

        def get_all_positions(self):
            return []

        def get_account(self):
            return SimpleNamespace(equity="100000", buying_power="100000")

    monkeypatch.setattr(
        execution_main,
        "_select_trading_client",
        lambda *_args, **_kwargs: _DummyTradingClient(),
    )
    monkeypatch.setattr(
        execution_main.book_router,
        "select_trading_client",
        lambda *_args, **_kwargs: _DummyTradingClient(),
    )
    sys.modules["execution_v2.market_data"] = SimpleNamespace(from_env=lambda: SimpleNamespace())
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)

    called = {"exits": False, "buy_loop": False}

    def _mark_exits_called(**_kwargs):
        called["exits"] = True

    def _raise_if_called(*_args, **_kwargs):
        called["buy_loop"] = True
        raise AssertionError("buy_loop should not be called during settle delay")

    monkeypatch.setattr(execution_main.exits, "manage_positions", _mark_exits_called)
    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", _raise_if_called)

    cfg = SimpleNamespace(
        candidates_csv=str(candidates_path),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(tmp_path / "execution.sqlite"),
        execution_mode="ALPACA_PAPER",
        dry_run=False,
        poll_seconds=300,
        ignore_market_hours=False,
    )

    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    decision = _read_latest_decision(latest_path)
    block_codes = {block["code"] for block in decision["gates"]["blocks"]}
    assert "market_settle_delay" in block_codes
    assert called["exits"] is True
    assert called["buy_loop"] is False
