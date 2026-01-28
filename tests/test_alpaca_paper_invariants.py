from __future__ import annotations

import json
import sys
import types
import uuid
from datetime import datetime, timezone

import pytest

from execution_v2 import alpaca_paper


class _DummyRequests(types.ModuleType):
    def post(self, *args, **kwargs):  # type: ignore[override]
        class _Resp:
            status_code = 200
            text = ""

        return _Resp()


sys.modules.setdefault("requests", _DummyRequests("requests"))

from execution_v2 import execution_main


def test_alpaca_paper_uses_trading_client(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            if "base_url" in kwargs:
                raise AssertionError("base_url should not be used for TradingClient")
            assert kwargs.get("url_override") == "https://paper-api.alpaca.markets"
            self.args = args
            self.kwargs = kwargs

    alpaca_module = types.ModuleType("alpaca")
    trading_module = types.ModuleType("alpaca.trading")
    client_module = types.ModuleType("alpaca.trading.client")
    client_module.TradingClient = DummyClient

    sys.modules["alpaca"] = alpaca_module
    sys.modules["alpaca.trading"] = trading_module
    sys.modules["alpaca.trading.client"] = client_module

    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets/")

    client = execution_main._get_alpaca_paper_trading_client()
    assert isinstance(client, DummyClient)


def test_alpaca_paper_requires_paper_base_url(monkeypatch) -> None:
    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    alpaca_module = types.ModuleType("alpaca")
    trading_module = types.ModuleType("alpaca.trading")
    client_module = types.ModuleType("alpaca.trading.client")
    client_module.TradingClient = DummyClient

    sys.modules["alpaca"] = alpaca_module
    sys.modules["alpaca.trading"] = trading_module
    sys.modules["alpaca.trading.client"] = client_module

    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets")

    with pytest.raises(RuntimeError, match="APCA_API_BASE_URL must be"):
        execution_main._get_alpaca_paper_trading_client()


def test_dry_run_overrides_alpaca_paper_client(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTION_MODE", "ALPACA_PAPER")
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    execution_mode = execution_main._resolve_execution_mode()

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("TradingClient should not be constructed in DRY_RUN")

    alpaca_module = types.ModuleType("alpaca")
    trading_module = types.ModuleType("alpaca.trading")
    client_module = types.ModuleType("alpaca.trading.client")
    client_module.TradingClient = DummyClient

    sys.modules["alpaca"] = alpaca_module
    sys.modules["alpaca.trading"] = trading_module
    sys.modules["alpaca.trading.client"] = client_module

    assert execution_mode == "DRY_RUN"
    with pytest.raises(RuntimeError, match="DRY_RUN=1 set"):
        execution_main._get_alpaca_paper_trading_client()


def test_alpaca_paper_idempotent_ledger(tmp_path) -> None:
    date_ny = "2024-01-02"
    path = alpaca_paper.ledger_path(tmp_path, date_ny)
    event = {
        "intent_id": "intent-1",
        "date_ny": date_ny,
        "execution_mode": "ALPACA_PAPER",
        "event_type": "ORDER_STATUS",
    }

    written_first, skipped_first = alpaca_paper.append_events(path, [event])
    written_second, skipped_second = alpaca_paper.append_events(path, [event])

    assert written_first == 1
    assert skipped_first == 0
    assert written_second == 0
    assert skipped_second == 1
    assert len(path.read_text().strip().splitlines()) == 1


def test_alpaca_paper_ledger_location(tmp_path) -> None:
    date_ny = "2024-01-02"
    path = alpaca_paper.ledger_path(tmp_path, date_ny)
    assert str(path).endswith(f"ledger/ALPACA_PAPER/{date_ny}.jsonl")


def test_alpaca_paper_serializes_uuid_order_id(tmp_path) -> None:
    order_id = uuid.uuid4()
    now_utc = datetime(2024, 1, 2, 15, 4, tzinfo=timezone.utc)
    order = types.SimpleNamespace(
        id=order_id,
        status="filled",
        filled_qty="10",
        filled_avg_price="12.34",
        filled_at=now_utc,
        created_at=now_utc,
    )
    event = alpaca_paper.build_order_event(
        intent_id="intent-uuid",
        symbol="AAA",
        qty=10,
        ref_price=12.34,
        order=order,
        now_utc=now_utc,
    )
    path = tmp_path / "ledger.jsonl"

    written, skipped = alpaca_paper.append_events(path, [event])

    assert written == 1
    assert skipped == 0
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["alpaca_order_id"] == str(order_id)
