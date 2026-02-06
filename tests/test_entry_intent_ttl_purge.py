from execution_v2.config_types import EntryIntent
from execution_v2.state_store import StateStore


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


def test_purge_stale_entry_intents_deletes_only_beyond_ttl(tmp_path) -> None:
    store = StateStore(str(tmp_path / "state.sqlite"))
    now_ts = 1_700_000_000.0
    within_ttl = now_ts - 1_800.0
    stale = now_ts - 7_200.0
    future = now_ts + 120.0

    store.put_entry_intent(_intent("WITHIN", within_ttl))
    store.put_entry_intent(_intent("STALE", stale))
    store.put_entry_intent(_intent("FUTURE", future))

    result = store.purge_stale_entry_intents(now_ts, ttl_sec=3_600)

    assert result["purged_count"] == 1
    assert result["oldest_age_sec"] == 7_200.0
    assert result["min_sched"] == stale
    assert result["max_sched"] == stale
    assert store.get_entry_intent("STALE") is None
    assert store.get_entry_intent("WITHIN") is not None
    assert store.get_entry_intent("FUTURE") is not None
    assert store.count_due_entry_intents(now_ts) == 1


def test_reschedule_due_entry_intents_updates_only_due_rows(tmp_path) -> None:
    store = StateStore(str(tmp_path / "state.sqlite"))
    now_ts = 1_700_100_000.0
    new_scheduled_at = now_ts + 300.0

    store.put_entry_intent(_intent("DUE_A", now_ts - 10.0))
    store.put_entry_intent(_intent("DUE_B", now_ts))
    store.put_entry_intent(_intent("FUTURE", now_ts + 500.0))

    result = store.reschedule_due_entry_intents(now_ts, new_scheduled_at=new_scheduled_at)

    assert result["rescheduled_count"] == 2
    assert result["new_scheduled_at"] == new_scheduled_at
    assert store.count_due_entry_intents(now_ts) == 0
    assert store.get_entry_intent("DUE_A").scheduled_entry_at == new_scheduled_at
    assert store.get_entry_intent("DUE_B").scheduled_entry_at == new_scheduled_at
    assert store.get_entry_intent("FUTURE").scheduled_entry_at == now_ts + 500.0
