import types
import pytest

from execution_v2.exits import manage_positions, ExitConfig

class DummyPos:
    symbol = "TEST"
    qty = "10"
    avg_entry_price = "100"
    current_price = "105"

class DummyTradingClient:
    def get_all_positions(self):
        return [DummyPos()]

class ExplodingMD:
    def get_intraday_bars(self, *a, **k):
        raise AssertionError("intraday MD should not be called during entry delay")

    def get_daily_bars(self, *a, **k):
        raise AssertionError("daily MD should not be called during entry delay")

def test_entry_delay_skips_md_when_stop_exists(monkeypatch, tmp_path):
    # Force an existing stop to be detected
    from execution_v2 import exits
    monkeypatch.setattr(
        exits,
        "_read_existing_stop",
        lambda *a, **k: 95.0,
    )

    manage_positions(
        trading_client=DummyTradingClient(),
        md=ExplodingMD(),
        cfg=ExitConfig.from_env(),
        repo_root=tmp_path,
        dry_run=True,
        log=lambda _: None,
        entry_delay_active=True,
    )
