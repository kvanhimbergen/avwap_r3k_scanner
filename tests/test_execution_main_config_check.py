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


def test_config_check_passes_in_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("EXECUTION_MODE", raising=False)

    ok, issues = execution_main.run_config_check(state_dir=str(tmp_path))

    assert ok is True
    assert issues == []


def test_config_check_flags_missing_alpaca_paper_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "ALPACA_PAPER")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_BASE_URL", raising=False)

    ok, issues = execution_main.run_config_check(state_dir=str(tmp_path))

    assert ok is False
    assert "missing:APCA_API_KEY_ID" in issues
    assert "missing:APCA_API_SECRET_KEY" in issues
    assert "missing:APCA_API_BASE_URL" in issues
