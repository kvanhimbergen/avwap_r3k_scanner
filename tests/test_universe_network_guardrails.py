import builtins
import logging
import sys

import pytest

pd = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from config import cfg
import universe


def test_get_universe_metrics_disallows_network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIVERSE_ALLOW_NETWORK", "0")

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] == "yfinance":
            raise AssertionError("yfinance import attempted while network is disallowed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    already_loaded = "yfinance" in sys.modules
    with pytest.raises(
        RuntimeError,
        match="Universe metrics requested but network access is disallowed",
    ):
        cfg.get_universe_metrics(["AAPL"])

    if not already_loaded:
        assert "yfinance" not in sys.modules


def test_apply_universe_rules_skips_metrics_when_network_disallowed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("UNIVERSE_ALLOW_NETWORK", "0")

    def _raise_if_called(*_args, **_kwargs):
        raise AssertionError("get_universe_metrics should not be called when network is disallowed")

    monkeypatch.setattr(cfg, "get_universe_metrics", _raise_if_called)

    df = pd.DataFrame({"Ticker": ["AAPL"]})
    rules = {"liquidity": {"min_price": 1.0}}

    with caplog.at_level(logging.WARNING):
        out = universe.apply_universe_rules(df, rules)

    assert out.equals(df)
    assert any("universe_network_disallowed" in record.message for record in caplog.records)
