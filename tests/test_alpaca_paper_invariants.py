from __future__ import annotations

import sys
import types

from execution_v2 import alpaca_paper


class _DummyRequests(types.ModuleType):
    def post(self, *args, **kwargs):  # type: ignore[override]
        class _Resp:
            status_code = 200
            text = ""

        return _Resp()


sys.modules.setdefault("requests", _DummyRequests("requests"))
sys.modules.setdefault("pandas", types.ModuleType("pandas"))

from execution_v2 import execution_main


def test_alpaca_paper_uses_trading_client(monkeypatch) -> None:
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

    monkeypatch.setenv("ALPACA_API_KEY_PAPER", "key")
    monkeypatch.setenv("ALPACA_API_SECRET_PAPER", "secret")
    monkeypatch.setenv("ALPACA_BASE_URL_PAPER", "https://paper.example.test")

    client = execution_main._get_alpaca_paper_trading_client()
    assert isinstance(client, DummyClient)


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
