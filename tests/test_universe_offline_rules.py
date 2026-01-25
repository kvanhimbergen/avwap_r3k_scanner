import pandas as pd

import universe


def test_apply_universe_rules_offline_never_calls_provider(monkeypatch):
    # Liquidity rules present forces the code path that would normally request metrics.
    rules = {"liquidity": {"min_avg_dollar_volume_20d": 1_000_000}}

    df = pd.DataFrame({"Ticker": ["AAPL", "MSFT"]})

    def _boom(_tickers):
        raise AssertionError("metrics provider must not be called when allow_network=False")

    monkeypatch.setattr(universe.cfg, "get_universe_metrics", _boom, raising=True)

    out = universe.apply_universe_rules(df, rules, allow_network=False)

    # Fail-open offline: no filtering should occur without metrics.
    assert out.equals(df)
