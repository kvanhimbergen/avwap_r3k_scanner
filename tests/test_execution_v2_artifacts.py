import json
import sys
from types import SimpleNamespace

import pytest

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import execution_main


class _DummyStore:
    def __init__(self, *_args, **_kwargs) -> None:
        pass


def test_market_closed_cycle_writes_only_heartbeat(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text("symbol\n", encoding="utf-8")
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(execution_main, "StateStore", _DummyStore)
    monkeypatch.setattr(
        execution_main.clocks,
        "now_snapshot",
        lambda: SimpleNamespace(market_open=False),
    )
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)

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
    assert not (state_dir / "portfolio_decision_latest.json").exists()
    assert not (tmp_path / "ledger" / "PORTFOLIO_DECISIONS").exists()

    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["market_is_open"] is False
    assert "market_closed" in heartbeat["blocks"]


def test_alpaca_paper_missing_creds_skips_writes(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)

    cfg = SimpleNamespace(
        candidates_csv=str(tmp_path / "daily_candidates.csv"),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(tmp_path / "execution.sqlite"),
        execution_mode="ALPACA_PAPER",
        dry_run=False,
        poll_seconds=300,
        ignore_market_hours=False,
    )

    with pytest.raises(RuntimeError, match="Missing Alpaca API credentials in environment"):
        execution_main.run_once(cfg)

    assert not (state_dir / "execution_heartbeat.json").exists()
    assert not (state_dir / "portfolio_decision_latest.json").exists()
    assert not (tmp_path / "ledger" / "PORTFOLIO_DECISIONS").exists()
