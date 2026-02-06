import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import clocks, execution_main
from execution_v2.config_types import EntryIntent
from execution_v2.state_store import StateStore


def _cfg(tmp_path, db_path):
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text("symbol\n", encoding="utf-8")
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


def _intent(symbol: str, scheduled_entry_at: float) -> EntryIntent:
    return EntryIntent(
        strategy_id="core",
        symbol=symbol,
        pivot_level=10.0,
        boh_confirmed_at=scheduled_entry_at - 30.0,
        scheduled_entry_at=scheduled_entry_at,
        size_shares=10,
        stop_loss=9.5,
        take_profit=11.0,
        ref_price=10.0,
        dist_pct=0.5,
    )


def test_purge_runs_even_when_market_closed_cycle_returns_early(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    db_path = tmp_path / "execution.sqlite"
    now_ts = datetime.now(timezone.utc).timestamp()

    store = StateStore(str(db_path))
    store.put_entry_intent(_intent("STALE", now_ts - 7_200.0))
    store.put_entry_intent(_intent("FRESH", now_ts - 300.0))

    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("ENTRY_INTENT_TTL_SEC", "3600")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)
    now_utc = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    monkeypatch.setattr(
        execution_main,
        "_market_open",
        lambda *_args, **_kwargs: (
            False,
            now_utc.astimezone(clocks.ET),
            "clock_snapshot",
            None,
        ),
    )

    execution_main.run_once(_cfg(tmp_path, db_path))

    store_after = StateStore(str(db_path))
    assert store_after.get_entry_intent("STALE") is None
    assert store_after.get_entry_intent("FRESH") is not None

    latest = json.loads((state_dir / "portfolio_decision_latest.json").read_text(encoding="utf-8"))
    reason_counts = latest.get("actions", {}).get("skipped_reason_counts", {})
    assert reason_counts.get("entry_intent_ttl_purged") == 1
    assert latest["intents_meta"]["entry_intent_lifecycle"]["purge"]["purged_count"] == 1


def test_gate_reschedule_enabled_requeues_due_intents_and_tracks_counts(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    db_path = tmp_path / "execution.sqlite"
    now_utc = datetime.now(timezone.utc)
    now_ts = now_utc.timestamp()
    future_gate_dt = (now_utc + timedelta(days=1)).astimezone(clocks.ET).replace(
        hour=9, minute=35, second=0, microsecond=0
    )
    expected_new_sched = (
        datetime.combine(future_gate_dt.date(), clocks.REG_OPEN, tzinfo=clocks.ET)
        + timedelta(minutes=20)
    ).timestamp()

    store = StateStore(str(db_path))
    store.put_entry_intent(_intent("DUE", now_ts - 120.0))
    store.put_entry_intent(_intent("STALE", now_ts - 7_200.0))

    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("ENTRY_INTENT_TTL_SEC", "3600")
    monkeypatch.setenv("ENTRY_INTENT_RESCHEDULE_ON_GATE", "1")
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "20")
    monkeypatch.setenv("MARKET_SETTLE_MINUTES", "0")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)
    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        execution_main,
        "_market_open",
        lambda *_args, **_kwargs: (
            True,
            future_gate_dt,
            "clock_snapshot",
            None,
        ),
    )

    execution_main.run_once(_cfg(tmp_path, db_path))

    store_after = StateStore(str(db_path))
    due_intent = store_after.get_entry_intent("DUE")
    assert due_intent is not None
    assert due_intent.scheduled_entry_at == expected_new_sched
    assert store_after.get_entry_intent("STALE") is None

    latest = json.loads((state_dir / "portfolio_decision_latest.json").read_text(encoding="utf-8"))
    reason_counts = latest.get("actions", {}).get("skipped_reason_counts", {})
    assert reason_counts.get("entry_intent_ttl_purged") == 1
    assert reason_counts.get("entry_intent_rescheduled_entry_delay") == 1
    lifecycle = latest["intents_meta"]["entry_intent_lifecycle"]
    assert lifecycle["purge"]["purged_count"] == 1
    assert lifecycle["reschedules"][0]["rescheduled_count"] == 1
