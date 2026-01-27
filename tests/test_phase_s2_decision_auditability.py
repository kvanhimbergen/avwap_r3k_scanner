from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import execution_main
from execution_v2.config_types import EntryIntent
from execution_v2.portfolio_s2_enforcement import (
    REASON_MAX_DAILY_LOSS,
    REASON_MISSING_PNL,
    build_enforcement_snapshot,
    enforce_sleeves,
)
from execution_v2.strategy_sleeves import SleeveConfig, StrategySleeve, load_sleeve_config


def _entry(strategy_id: str, symbol: str) -> EntryIntent:
    return EntryIntent(
        strategy_id=strategy_id,
        symbol=symbol,
        pivot_level=0.0,
        boh_confirmed_at=1.0,
        scheduled_entry_at=2.0,
        size_shares=1,
        stop_loss=0.0,
        take_profit=0.0,
        ref_price=100.0,
        dist_pct=0.0,
    )


def _build_config(daily_pnl: SleeveConfig, max_loss: float | None) -> SleeveConfig:
    return SleeveConfig(
        sleeves={"S1_AVWAP_CORE": StrategySleeve(max_daily_loss_usd=max_loss)},
        allow_unsleeved=False,
        allow_symbol_overlap=False,
        daily_pnl_by_strategy=daily_pnl.daily_pnl_by_strategy,
        daily_pnl_source=daily_pnl.daily_pnl_source,
        daily_pnl_parse_error=daily_pnl.daily_pnl_parse_error,
    )


def _build_decision_record() -> dict:
    cfg = SimpleNamespace(execution_mode="DRY_RUN", poll_seconds=1)
    now_utc = datetime.now(timezone.utc)
    candidates_snapshot = {"path": "candidates.csv", "mtime_utc": now_utc.isoformat()}
    return execution_main._init_decision_record(cfg, candidates_snapshot, now_utc)


def test_s2_daily_pnl_present_pass(monkeypatch) -> None:
    monkeypatch.setenv("S2_DAILY_PNL_JSON", '{"S1_AVWAP_CORE": 0.0}')
    parsed, _ = load_sleeve_config()
    config = _build_config(parsed, max_loss=250.0)
    result = enforce_sleeves(intents=[_entry("S1_AVWAP_CORE", "AAPL")], positions=[], config=config)

    snapshot = build_enforcement_snapshot(result=result, config=config)
    decision_record = _build_decision_record()
    execution_main._record_s2_inputs(decision_record, config)

    assert decision_record["inputs"]["s2_daily_pnl_by_strategy"]["S1_AVWAP_CORE"] == 0.0
    assert snapshot["strategy_summaries"]["S1_AVWAP_CORE"]["daily_pnl_usd"] == 0.0
    assert REASON_MAX_DAILY_LOSS not in snapshot["reason_counts"]


def test_s2_daily_pnl_present_block(monkeypatch) -> None:
    monkeypatch.setenv("S2_DAILY_PNL_JSON", '{"S1_AVWAP_CORE": -1000.0}')
    parsed, _ = load_sleeve_config()
    config = _build_config(parsed, max_loss=250.0)
    result = enforce_sleeves(intents=[_entry("S1_AVWAP_CORE", "AAPL")], positions=[], config=config)

    snapshot = build_enforcement_snapshot(result=result, config=config)
    decision_record = _build_decision_record()
    execution_main._record_s2_inputs(decision_record, config)

    assert decision_record["inputs"]["s2_daily_pnl_by_strategy"]["S1_AVWAP_CORE"] == -1000.0
    assert snapshot["strategy_summaries"]["S1_AVWAP_CORE"]["daily_pnl_usd"] == -1000.0
    assert snapshot["reason_counts"][REASON_MAX_DAILY_LOSS] == 1
    assert result.blocked[0].reason_codes == [REASON_MAX_DAILY_LOSS]


def test_s2_daily_pnl_missing_blocks(monkeypatch) -> None:
    monkeypatch.delenv("S2_DAILY_PNL_JSON", raising=False)
    parsed, _ = load_sleeve_config()
    config = _build_config(parsed, max_loss=250.0)
    result = enforce_sleeves(intents=[_entry("S1_AVWAP_CORE", "AAPL")], positions=[], config=config)

    snapshot = build_enforcement_snapshot(result=result, config=config)
    decision_record = _build_decision_record()
    execution_main._record_s2_inputs(decision_record, config)

    assert decision_record["inputs"]["s2_daily_pnl_by_strategy"] == {}
    assert snapshot["strategy_summaries"]["S1_AVWAP_CORE"]["daily_pnl_usd"] is None
    assert snapshot["reason_counts"][REASON_MISSING_PNL] == 1


def test_s2_daily_pnl_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("S2_DAILY_PNL_JSON", "not-json")
    parsed, _ = load_sleeve_config()
    config = _build_config(parsed, max_loss=250.0)
    result = enforce_sleeves(intents=[_entry("S1_AVWAP_CORE", "AAPL")], positions=[], config=config)

    snapshot = build_enforcement_snapshot(result=result, config=config)
    decision_record = _build_decision_record()
    execution_main._record_s2_inputs(decision_record, config)

    assert decision_record["inputs"]["s2_daily_pnl_by_strategy"] == {}
    assert snapshot["pnl_parse_error"].startswith("daily_pnl_json_invalid")
    assert snapshot["strategy_summaries"]["S1_AVWAP_CORE"]["daily_pnl_usd"] is None
    assert snapshot["reason_counts"][REASON_MISSING_PNL] == 1


def test_intents_meta_created_but_empty_pre_s2(monkeypatch) -> None:
    monkeypatch.setenv("S2_DAILY_PNL_JSON", '{"S1_AVWAP_CORE": 0.0}')
    parsed, _ = load_sleeve_config()
    config = _build_config(parsed, max_loss=250.0)
    decision_record = _build_decision_record()
    execution_main._record_s2_inputs(decision_record, config)

    created = [
        _entry("S1_AVWAP_CORE", "AAPL"),
        _entry("S1_AVWAP_CORE", "MSFT"),
    ]
    decision_record["intents"]["intent_count"] = 0
    decision_record["intents"]["intents"] = []

    execution_main._update_intents_meta(
        decision_record,
        created_intents=created,
        entry_intents=[],
        approved_intents=[],
        s2_snapshot=None,
    )

    intents_meta = decision_record["intents_meta"]
    assert intents_meta["entry_intents_created_count"] == 2
    assert intents_meta["entry_intents_created_sample"]
    assert intents_meta["entry_intents_pre_s2_count"] == 0
    assert intents_meta["entry_intents_post_s2_count"] == 0
    assert decision_record["inputs"]["s2_daily_pnl_by_strategy"]["S1_AVWAP_CORE"] == 0.0


def test_intents_meta_counts_flow() -> None:
    decision_record = _build_decision_record()
    created = [
        _entry("S1_AVWAP_CORE", "AAPL"),
        _entry("S1_AVWAP_CORE", "MSFT"),
    ]
    entry_intents = created[:]
    approved = created[:1]

    execution_main._update_intents_meta(
        decision_record,
        created_intents=created,
        entry_intents=entry_intents,
        approved_intents=approved,
        s2_snapshot={"reason_counts": {REASON_MAX_DAILY_LOSS: 1}},
    )

    intents_meta = decision_record["intents_meta"]
    assert intents_meta["entry_intents_created_count"] >= intents_meta["entry_intents_pre_s2_count"]
    assert intents_meta["entry_intents_pre_s2_count"] >= intents_meta["entry_intents_post_s2_count"]
    assert intents_meta["drop_reason_counts"][REASON_MAX_DAILY_LOSS] == 1
