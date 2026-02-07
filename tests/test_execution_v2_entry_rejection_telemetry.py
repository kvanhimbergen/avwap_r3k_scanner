import json
import sys
from datetime import datetime
from types import SimpleNamespace

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import clocks, execution_main


def _cfg(tmp_path, db_path):
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text(
        "Symbol,Entry_Level,Stop_Loss,Target_R2,Entry_DistPct,Price\n"
        "AAA,10,9,12,1,10\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        base_dir=str(tmp_path),
        candidates_csv=str(candidates_path),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(db_path),
        execution_mode="DRY_RUN",
        dry_run=True,
        poll_seconds=300,
        ignore_market_hours=False,
    )


def _run_cycle_with_telemetry_stub(
    *,
    tmp_path,
    monkeypatch,
    rejected: list[tuple[str, str]],
    accepted: int,
    symbol_cap: int = 50,
):
    state_dir = tmp_path / "state"
    db_path = tmp_path / "execution.sqlite"
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET)

    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("ENTRY_REJECTION_REJECTED_SYMBOLS_MAX", str(symbol_cap))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        execution_main.clocks,
        "now_snapshot",
        lambda: SimpleNamespace(market_open=True, now_et=now_et),
    )
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)

    def _fake_buy_loop(*_args, **kwargs):
        telemetry = kwargs["rejection_telemetry"]
        for symbol, reason in rejected:
            telemetry.record_candidate()
            telemetry.record_rejected(symbol, reason)
        for _ in range(accepted):
            telemetry.record_candidate()
            telemetry.record_accepted()
        return accepted

    monkeypatch.setattr(
        execution_main.buy_loop,
        "evaluate_and_create_entry_intents",
        _fake_buy_loop,
    )

    execution_main.run_once(_cfg(tmp_path, db_path))
    latest_path = state_dir / "portfolio_decision_latest.json"
    return json.loads(latest_path.read_text(encoding="utf-8"))


def test_entry_rejection_telemetry_all_rejected(tmp_path, monkeypatch) -> None:
    payload = _run_cycle_with_telemetry_stub(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rejected=[
            ("AAA", "missing_market_data"),
            ("BBB", "boh_not_confirmed"),
            ("CCC", "existing_open_orders"),
        ],
        accepted=0,
    )
    telemetry = payload["intents_meta"]["entry_rejections"]

    assert telemetry["candidates_seen"] == 3
    assert telemetry["accepted"] == 0
    assert telemetry["rejected"] == 3
    assert telemetry["reason_counts"] == {
        "boh_not_confirmed": 1,
        "existing_open_orders": 1,
        "missing_market_data": 1,
    }
    assert telemetry["rejected_symbols"] == [
        {"symbol": "AAA", "reason": "missing_market_data"},
        {"symbol": "BBB", "reason": "boh_not_confirmed"},
        {"symbol": "CCC", "reason": "existing_open_orders"},
    ]
    assert telemetry["rejected_symbols_truncated"] == 0


def test_entry_rejection_telemetry_mixed_accept_and_reject(tmp_path, monkeypatch) -> None:
    payload = _run_cycle_with_telemetry_stub(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rejected=[
            ("AAA", "missing_market_data"),
            ("BBB", "boh_not_confirmed"),
        ],
        accepted=1,
    )
    telemetry = payload["intents_meta"]["entry_rejections"]

    assert telemetry["candidates_seen"] == 3
    assert telemetry["accepted"] == 1
    assert telemetry["rejected"] == 2
    assert telemetry["reason_counts"] == {
        "boh_not_confirmed": 1,
        "missing_market_data": 1,
    }
    assert telemetry["rejected_symbols"] == [
        {"symbol": "AAA", "reason": "missing_market_data"},
        {"symbol": "BBB", "reason": "boh_not_confirmed"},
    ]
    assert telemetry["rejected_symbols_truncated"] == 0


def test_entry_rejection_telemetry_rejected_symbols_truncation(tmp_path, monkeypatch) -> None:
    rejected = [(f"S{i:03d}", "boh_not_confirmed") for i in range(200)]
    payload = _run_cycle_with_telemetry_stub(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        rejected=rejected,
        accepted=0,
        symbol_cap=50,
    )
    telemetry = payload["intents_meta"]["entry_rejections"]

    assert telemetry["candidates_seen"] == 200
    assert telemetry["accepted"] == 0
    assert telemetry["rejected"] == 200
    assert telemetry["reason_counts"] == {"boh_not_confirmed": 200}
    assert len(telemetry["rejected_symbols"]) == 50
    assert telemetry["rejected_symbols_truncated"] == 150
