import sys
from types import SimpleNamespace

if "requests" not in sys.modules:
    sys.modules["requests"] = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=200, text=""),
        Session=object,
    )
if "pandas" not in sys.modules:
    sys.modules["pandas"] = SimpleNamespace(DataFrame=object)

from execution_v2 import execution_main


def test_dry_run_ledger_creates_state_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))

    intent = SimpleNamespace(symbol="AAPL", size_shares=5)

    result = execution_main._submit_market_entry(None, intent, dry_run=True)
    assert result == "dry-run"

    ledger_path = state_dir / "dry_run_ledger.json"
    assert ledger_path.exists()

    second = execution_main._submit_market_entry(None, intent, dry_run=True)
    assert second == "dry-run-skipped"


def test_dry_run_ledger_handles_unwritable_state_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "state-file"
    state_dir.write_text("not-a-directory")
    monkeypatch.setenv("AVWAP_STATE_DIR", str(state_dir))

    intent = SimpleNamespace(symbol="MSFT", size_shares=1)
    result = execution_main._submit_market_entry(None, intent, dry_run=True)
    assert result == "dry-run"
    ledger_path = state_dir / "dry_run_ledger.json"
    assert not ledger_path.exists()
