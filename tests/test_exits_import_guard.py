import importlib
import sys


def test_exits_import_guard_handles_missing_alpaca(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def _fake_find_spec(name, *args, **kwargs):
        if name.startswith("alpaca"):
            raise ModuleNotFoundError("No module named 'alpaca'")
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _fake_find_spec)
    sys.modules.pop("execution_v2.exits", None)
    exits = importlib.import_module("execution_v2.exits")

    assert hasattr(exits, "APIError")
    assert issubclass(exits.APIError, Exception)
