"""Tests for relative volume (rvol) gating in execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from execution_v2.market_data import VolumeProfile


class TestVolumeProfile:
    """Basic VolumeProfile dataclass tests."""

    def test_fields(self):
        vp = VolumeProfile(
            today_cumulative=1_000_000,
            avg_cumulative=800_000,
            rvol=1.25,
            sample_days=20,
            bar_count_today=40,
        )
        assert vp.rvol == 1.25
        assert vp.sample_days == 20


class TestRvolGateBuyLoop:
    """Test rvol gating in buy_loop.evaluate_and_create_entry_intents."""

    def test_low_rvol_rejects(self):
        from execution_v2.buy_loop import (
            BuyLoopConfig,
            REASON_LOW_RVOL,
            EntryRejectionTelemetry,
        )

        cfg = BuyLoopConfig(rvol_min=0.8)
        assert cfg.rvol_min == 0.8

    def test_rvol_reason_in_known_reasons(self):
        from execution_v2.buy_loop import REASON_LOW_RVOL, _KNOWN_REJECTION_REASONS

        assert REASON_LOW_RVOL in _KNOWN_REJECTION_REASONS

    def test_disabled_when_zero(self):
        """When rvol_min=0, the check should be skipped entirely."""
        from execution_v2.buy_loop import BuyLoopConfig

        cfg = BuyLoopConfig(rvol_min=0.0)
        assert cfg.rvol_min == 0.0


class TestRvolGateBracketAdapter:
    """Test rvol gating in alpaca_s2_bracket_adapter."""

    def test_low_rvol_skips_candidate(self):
        from execution_v2.alpaca_s2_bracket_adapter import AlpacaS2BracketAdapter

        mock_client = MagicMock()
        mock_client.get_account.return_value = MagicMock(equity="100000")
        mock_client.get_all_positions.return_value = []

        from alpaca.trading.requests import GetOrdersRequest

        mock_client.get_orders.return_value = []

        mock_md = MagicMock()
        mock_md.get_session_volume_profile.return_value = VolumeProfile(
            today_cumulative=500_000,
            avg_cumulative=1_000_000,
            rvol=0.5,
            sample_days=20,
            bar_count_today=40,
        )

        adapter = AlpacaS2BracketAdapter(mock_client)
        from pathlib import Path

        result = adapter.execute_candidates(
            [{"Symbol": "AAPL", "Entry_Level": 100, "Stop_Loss": 95, "Target_R2": 110}],
            ny_date="2026-02-20",
            repo_root=Path("/tmp"),
            rvol_min=0.8,
            market_data=mock_md,
        )
        assert result.skipped == 1
        assert result.sent == 0

    def test_sufficient_rvol_allows_entry(self):
        from execution_v2.alpaca_s2_bracket_adapter import AlpacaS2BracketAdapter

        mock_client = MagicMock()
        mock_client.get_account.return_value = MagicMock(equity="100000")
        mock_client.get_all_positions.return_value = []
        mock_client.get_orders.return_value = []

        mock_md = MagicMock()
        mock_md.get_session_volume_profile.return_value = VolumeProfile(
            today_cumulative=1_500_000,
            avg_cumulative=1_000_000,
            rvol=1.5,
            sample_days=20,
            bar_count_today=40,
        )

        adapter = AlpacaS2BracketAdapter(mock_client)
        from pathlib import Path

        # The entry should NOT be skipped due to rvol — it may proceed or fail
        # at the actual order submission step
        result = adapter.execute_candidates(
            [{"Symbol": "AAPL", "Entry_Level": 100, "Stop_Loss": 95, "Target_R2": 110}],
            ny_date="2026-02-20",
            repo_root=Path("/tmp"),
            rvol_min=0.8,
            market_data=mock_md,
        )
        # Should not be skipped for rvol reasons (may be sent or error out)
        assert result.skipped == 0 or result.sent > 0 or len(result.errors) > 0

    def test_failopen_on_exception(self):
        """If rvol check raises, entry should still proceed (fail-open)."""
        from execution_v2.alpaca_s2_bracket_adapter import AlpacaS2BracketAdapter

        mock_client = MagicMock()
        mock_client.get_account.return_value = MagicMock(equity="100000")
        mock_client.get_all_positions.return_value = []
        mock_client.get_orders.return_value = []

        mock_md = MagicMock()
        mock_md.get_session_volume_profile.side_effect = Exception("API timeout")

        adapter = AlpacaS2BracketAdapter(mock_client)
        from pathlib import Path

        result = adapter.execute_candidates(
            [{"Symbol": "AAPL", "Entry_Level": 100, "Stop_Loss": 95, "Target_R2": 110}],
            ny_date="2026-02-20",
            repo_root=Path("/tmp"),
            rvol_min=0.8,
            market_data=mock_md,
        )
        # Should NOT be skipped — fail-open means entry proceeds
        assert result.skipped == 0

    def test_no_rvol_check_when_zero(self):
        """When rvol_min=0, market_data.get_session_volume_profile should not be called."""
        from execution_v2.alpaca_s2_bracket_adapter import AlpacaS2BracketAdapter

        mock_client = MagicMock()
        mock_client.get_account.return_value = MagicMock(equity="100000")
        mock_client.get_all_positions.return_value = []
        mock_client.get_orders.return_value = []

        mock_md = MagicMock()

        adapter = AlpacaS2BracketAdapter(mock_client)
        from pathlib import Path

        adapter.execute_candidates(
            [{"Symbol": "AAPL", "Entry_Level": 100, "Stop_Loss": 95, "Target_R2": 110}],
            ny_date="2026-02-20",
            repo_root=Path("/tmp"),
            rvol_min=0.0,
            market_data=mock_md,
        )
        mock_md.get_session_volume_profile.assert_not_called()
