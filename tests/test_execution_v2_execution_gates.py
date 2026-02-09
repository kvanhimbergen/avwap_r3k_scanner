import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import clocks, execution_main, state_machine
from execution_v2.config_types import EntryIntent
from execution_v2.orders import OrderSpec, generate_idempotency_key
from execution_v2.portfolio_decision import PortfolioDecision, build_decision_hash


class DummyStore:
    def __init__(self, entry_intents: list[EntryIntent]) -> None:
        self.entry_intents = entry_intents
        self.used_keys: set[str] = set()
        self.submissions: list[dict] = []

    def list_positions(self):
        return []

    def pop_trim_intents(self):
        return []

    def pop_due_entry_intents(self, _now_ts):
        return list(self.entry_intents)

    def get_position(self, _symbol):
        return None

    def get_entry_fill(self, *_args, **_kwargs):
        return None

    def record_entry_fill(self, *_args, **_kwargs):
        return True

    def get_candidate_notes(self, _symbol):
        return None

    def has_order_idempotency_key(self, key: str) -> bool:
        return key in self.used_keys

    def record_order_once(self, key, *_args, **_kwargs):
        self.used_keys.add(key)
        return True

    def update_external_order_id(self, *_args, **_kwargs):
        return None

    def record_order_submission(self, **kwargs):
        self.submissions.append(kwargs)
        return True


class DummySleeveConfig:
    daily_pnl_by_strategy = {}
    daily_pnl_source = "test"
    daily_pnl_parse_error = None

    def to_snapshot(self):
        return {}


def _dummy_decision(intents, run_id: str, date_ny: str, constraints_snapshot: dict) -> PortfolioDecision:
    orders = []
    for intent in intents:
        key = generate_idempotency_key(intent.strategy_id, date_ny, intent.symbol, "buy", intent.qty)
        orders.append(
            OrderSpec(
                strategy_id=intent.strategy_id,
                symbol=intent.symbol,
                side=intent.side,
                qty=intent.qty,
                limit_price=1.0,
                tif="day",
                idempotency_key=key,
            )
        )
    payload = {
        "run_id": run_id,
        "date_ny": date_ny,
        "approved_orders": [order.__dict__ for order in orders],
        "rejected_intents": [],
        "constraints_snapshot": constraints_snapshot,
    }
    return PortfolioDecision(
        run_id=run_id,
        date_ny=date_ny,
        approved_orders=orders,
        rejected_intents=[],
        constraints_snapshot=constraints_snapshot,
        decision_hash=build_decision_hash(payload),
    )


def _patch_core(monkeypatch, state_dir, now_et, store):
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("APCA_API_BASE_URL", execution_main.PAPER_BASE_URL)
    monkeypatch.setattr(execution_main, "StateStore", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(execution_main, "maybe_send_heartbeat", lambda **_: None)
    monkeypatch.setattr(execution_main, "maybe_send_daily_summary", lambda **_: None)
    monkeypatch.setattr(execution_main, "_alpaca_clock_snapshot", lambda *_: (True, now_et))
    monkeypatch.setattr(execution_main, "_has_open_order_or_position", lambda *_: False)
    monkeypatch.setattr(execution_main, "slack_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(execution_main, "send_verbose_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", lambda *_a, **_k: 0)
    monkeypatch.setattr(execution_main.exits, "manage_positions", lambda **_kwargs: None)
    monkeypatch.setattr(execution_main.portfolio_decision_enforce, "enforcement_enabled", lambda: False)

    def _arbitrate(intents, *, constraints, run_id, date_ny, **_kwargs):
        return _dummy_decision(intents, run_id, date_ny, constraints.to_snapshot())

    monkeypatch.setattr(execution_main.portfolio_arbiter, "arbitrate_intents", _arbitrate)
    monkeypatch.setattr(
        execution_main.strategy_sleeves,
        "load_sleeve_config",
        lambda: (DummySleeveConfig(), []),
    )
    monkeypatch.setattr(
        execution_main.portfolio_s2_enforcement,
        "enforce_sleeves",
        lambda intents, positions, config: SimpleNamespace(
            approved=intents,
            blocked=[],
            blocked_all=False,
            strategy_summaries={},
            portfolio_summary={},
            reason_counts={},
            blocked_sample=[],
            errors=[],
        ),
    )
    monkeypatch.setattr(
        execution_main.portfolio_s2_enforcement,
        "build_enforcement_snapshot",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        execution_main.alpaca_paper,
        "append_events",
        lambda *_args, **_kwargs: ([], []),
    )
    monkeypatch.setattr(
        execution_main.alpaca_paper,
        "build_order_event",
        lambda *_args, **_kwargs: {"filled_qty": 0},
    )
    dummy_md = SimpleNamespace(
        get_last_two_closed_10m=lambda *_args, **_kwargs: [],
        get_daily_bars=lambda *_args, **_kwargs: [],
        get_intraday_bars=lambda *_args, **_kwargs: [],
    )
    sys.modules["execution_v2.market_data"] = SimpleNamespace(from_env=lambda: dummy_md)

    class DummyTradingClient:
        def get_all_positions(self):
            return []

        def get_account(self):
            return SimpleNamespace(equity="100000", buying_power="100000")

        def submit_order(self, _order):
            return SimpleNamespace(id="order")

    monkeypatch.setattr(
        execution_main,
        "_select_trading_client",
        lambda *_args, **_kwargs: DummyTradingClient(),
    )
    monkeypatch.setattr(
        execution_main.book_router,
        "select_trading_client",
        lambda *_args, **_kwargs: DummyTradingClient(),
    )


def _base_cfg(tmp_path):
    candidates_path = tmp_path / "daily_candidates.csv"
    candidates_path.write_text("symbol\n", encoding="utf-8")
    return SimpleNamespace(
        base_dir=str(tmp_path),
        candidates_csv=str(candidates_path),
        entry_delay_min_sec=0,
        entry_delay_max_sec=0,
        db_path=str(tmp_path / "execution.sqlite"),
        execution_mode="ALPACA_PAPER",
        dry_run=False,
        poll_seconds=300,
        ignore_market_hours=False,
    )


def test_entry_delay_blocks_entries_allows_exits(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 9, 35, tzinfo=clocks.ET)
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "20")
    store = DummyStore([])
    _patch_core(monkeypatch, state_dir, now_et, store)

    called = {"buy_loop": False, "exits": False}

    def _mark_buy(*_args, **_kwargs):
        called["buy_loop"] = True
        return 0

    def _mark_exits(**_kwargs):
        called["exits"] = True

    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", _mark_buy)
    monkeypatch.setattr(execution_main.exits, "manage_positions", _mark_exits)

    cfg = _base_cfg(tmp_path)
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    decision = json.loads(latest_path.read_text(encoding="utf-8"))
    block_codes = {block["code"] for block in decision["gates"]["blocks"]}
    assert "entry_delay_after_open" in block_codes
    assert called["buy_loop"] is False
    assert called["exits"] is True


def test_entry_delay_allows_entries_after_delay(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 9, 55, tzinfo=clocks.ET)
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "20")
    store = DummyStore([])
    _patch_core(monkeypatch, state_dir, now_et, store)

    called = {"buy_loop": False}

    def _mark_buy(*_args, **_kwargs):
        called["buy_loop"] = True
        return 0

    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", _mark_buy)

    cfg = _base_cfg(tmp_path)
    execution_main.run_once(cfg)

    assert called["buy_loop"] is True


def test_idempotency_partial_submission_and_retry(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET)
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "0")
    now_ts = time.time()
    intents = [
        EntryIntent(
            strategy_id="core",
            symbol="ALSN",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=10,
            stop_loss=1.0,
            take_profit=2.0,
            ref_price=1.0,
            dist_pct=0.1,
        ),
        EntryIntent(
            strategy_id="core",
            symbol="HP",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=11,
            stop_loss=1.0,
            take_profit=2.0,
            ref_price=1.0,
            dist_pct=0.1,
        ),
        EntryIntent(
            strategy_id="core",
            symbol="AXSM",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=12,
            stop_loss=1.0,
            take_profit=2.0,
            ref_price=1.0,
            dist_pct=0.1,
        ),
    ]
    store = DummyStore(intents)
    _patch_core(monkeypatch, state_dir, now_et, store)
    date_ny = execution_main.paper_sim.resolve_date_ny(datetime.now(timezone.utc))

    calls = []

    def _submit(trading_client, intent, dry_run):
        calls.append(intent.symbol)
        if intent.symbol == "AXSM":
            raise RuntimeError("submission failed")
        return f"order-{intent.symbol}"

    monkeypatch.setattr(execution_main, "_submit_market_entry", _submit)

    cfg = _base_cfg(tmp_path)
    execution_main.run_once(cfg)

    assert set(store.used_keys) == {
        generate_idempotency_key("core", date_ny, "ALSN", "buy", 10),
        generate_idempotency_key("core", date_ny, "HP", "buy", 11),
    }
    assert "AXSM" in calls

    calls.clear()

    def _submit_retry(trading_client, intent, dry_run):
        calls.append(intent.symbol)
        return f"order-{intent.symbol}"

    monkeypatch.setattr(execution_main, "_submit_market_entry", _submit_retry)
    execution_main.run_once(cfg)

    assert calls == ["AXSM"]


def test_symbol_state_blocks_reentry(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET)
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "0")
    now_ts = time.time()
    intents = [
        EntryIntent(
            strategy_id="core",
            symbol="AAPL",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=5,
            stop_loss=1.0,
            take_profit=2.0,
            ref_price=1.0,
            dist_pct=0.1,
        )
    ]
    store = DummyStore(intents)
    _patch_core(monkeypatch, state_dir, now_et, store)

    date_ny = execution_main.paper_sim.resolve_date_ny(datetime.now(timezone.utc))
    state_store = state_machine.SymbolExecutionStateStore(date_ny, state_dir=state_dir)
    state_store.transition("AAPL", "ENTERING", now_utc=datetime.now(timezone.utc))
    state_store.save()

    calls = []
    monkeypatch.setattr(
        execution_main,
        "_submit_market_entry",
        lambda *_args, **_kwargs: calls.append("AAPL") or "order-AAPL",
    )

    cfg = _base_cfg(tmp_path)
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    decision = json.loads(latest_path.read_text(encoding="utf-8"))
    reasons = {item["reason"] for item in decision["actions"]["skipped"]}
    assert "symbol_state_not_flat" in reasons
    assert calls == []


def test_consumed_entry_blocks_reentry(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET)
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "0")
    now_ts = time.time()
    intents = [
        EntryIntent(
            strategy_id="core",
            symbol="MSFT",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=5,
            stop_loss=1.0,
            take_profit=2.0,
            ref_price=1.0,
            dist_pct=0.1,
        )
    ]
    store = DummyStore(intents)
    _patch_core(monkeypatch, state_dir, now_et, store)

    date_ny = execution_main.paper_sim.resolve_date_ny(datetime.now(timezone.utc))
    consumed_store = state_machine.ConsumedEntriesStore(date_ny, state_dir=state_dir)
    consumed_store.mark("MSFT", datetime.now(timezone.utc))

    calls = []
    monkeypatch.setattr(
        execution_main,
        "_submit_market_entry",
        lambda *_args, **_kwargs: calls.append("MSFT") or "order-MSFT",
    )

    cfg = _base_cfg(tmp_path)
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    decision = json.loads(latest_path.read_text(encoding="utf-8"))
    reasons = {item["reason"] for item in decision["actions"]["skipped"]}
    assert "already_consumed_today" in reasons
    assert calls == []


def test_candidates_stale_blocks_entry_creation(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET)
    store = DummyStore([])
    _patch_core(monkeypatch, state_dir, now_et, store)

    called = {"buy_loop": False}

    def _mark_buy(*_args, **_kwargs):
        called["buy_loop"] = True
        return 0

    monkeypatch.setattr(execution_main.buy_loop, "evaluate_and_create_entry_intents", _mark_buy)

    cfg = _base_cfg(tmp_path)
    candidates_path = Path(cfg.candidates_csv)
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    candidates_path.touch()
    os.utime(candidates_path, (stale_ts, stale_ts))
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    decision = json.loads(latest_path.read_text(encoding="utf-8"))
    block_codes = {block["code"] for block in decision["gates"]["blocks"]}
    assert "candidates_stale" in block_codes
    assert called["buy_loop"] is False


def test_projected_max_positions_blocks_second_order_same_cycle(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=clocks.ET)
    monkeypatch.setenv("ENTRY_DELAY_AFTER_OPEN_MINUTES", "0")
    monkeypatch.setenv("MAX_LIVE_POSITIONS", "1")
    now_ts = time.time()
    intents = [
        EntryIntent(
            strategy_id="core",
            symbol="AAA",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=5,
            stop_loss=0.9,
            take_profit=1.2,
            ref_price=1.0,
            dist_pct=0.1,
        ),
        EntryIntent(
            strategy_id="core",
            symbol="BBB",
            pivot_level=1.0,
            boh_confirmed_at=now_ts,
            scheduled_entry_at=now_ts,
            size_shares=5,
            stop_loss=0.9,
            take_profit=1.2,
            ref_price=1.0,
            dist_pct=0.1,
        ),
    ]
    store = DummyStore(intents)
    _patch_core(monkeypatch, state_dir, now_et, store)
    monkeypatch.setattr(
        execution_main,
        "_submit_market_entry",
        lambda *_args, **_kwargs: "order-id",
    )

    cfg = _base_cfg(tmp_path)
    execution_main.run_once(cfg)

    latest_path = state_dir / "portfolio_decision_latest.json"
    decision = json.loads(latest_path.read_text(encoding="utf-8"))
    submitted_symbols = [row["symbol"] for row in decision["actions"]["submitted_orders"]]
    skipped_reasons = {item["reason"] for item in decision["actions"]["skipped"]}
    assert len(submitted_symbols) == 1
    assert "max positions reached" in skipped_reasons
