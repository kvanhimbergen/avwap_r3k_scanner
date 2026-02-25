"""Tests for sector relative strength computation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestComputeSectorRelativeStrength:
    """Test compute_sector_relative_strength from scan_engine."""

    def test_basic_rs_outperforming(self):
        """Sector with higher return than SPY should have RS > 1.0."""
        from scan_engine import compute_sector_relative_strength

        # Sector returned 5%, SPY returned 3%
        # RS = (1.05) / (1.03) ≈ 1.0194
        mock_client = MagicMock()
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2026-01-01", periods=20, freq="B")
        spy_close = np.linspace(100, 103, 20)
        xlk_close = np.linspace(100, 105, 20)

        rows = []
        for i, d in enumerate(dates):
            rows.append({"symbol": "SPY", "timestamp": d, "open": spy_close[i], "high": spy_close[i]+1, "low": spy_close[i]-1, "close": spy_close[i], "volume": 1e6})
            rows.append({"symbol": "XLK", "timestamp": d, "open": xlk_close[i], "high": xlk_close[i]+1, "low": xlk_close[i]-1, "close": xlk_close[i], "volume": 1e6})

        mock_df = pd.DataFrame(rows)
        mock_bars_result = MagicMock()
        mock_bars_result.df = mock_df
        mock_client.get_stock_bars.return_value = mock_bars_result

        result = compute_sector_relative_strength(
            mock_client,
            sector_etfs={"Information Technology": "XLK"},
            lookback_days=20,
        )

        assert "Information Technology" in result
        assert result["Information Technology"] > 1.0

    def test_basic_rs_underperforming(self):
        """Sector with lower return than SPY should have RS < 1.0."""
        from scan_engine import compute_sector_relative_strength

        mock_client = MagicMock()
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2026-01-01", periods=20, freq="B")
        spy_close = np.linspace(100, 105, 20)
        xlk_close = np.linspace(100, 101, 20)

        rows = []
        for i, d in enumerate(dates):
            rows.append({"symbol": "SPY", "timestamp": d, "open": spy_close[i], "high": spy_close[i]+1, "low": spy_close[i]-1, "close": spy_close[i], "volume": 1e6})
            rows.append({"symbol": "XLK", "timestamp": d, "open": xlk_close[i], "high": xlk_close[i]+1, "low": xlk_close[i]-1, "close": xlk_close[i], "volume": 1e6})

        mock_df = pd.DataFrame(rows)
        mock_bars_result = MagicMock()
        mock_bars_result.df = mock_df
        mock_client.get_stock_bars.return_value = mock_bars_result

        result = compute_sector_relative_strength(
            mock_client,
            sector_etfs={"Information Technology": "XLK"},
            lookback_days=20,
        )

        assert result["Information Technology"] < 1.0

    def test_empty_data_returns_1(self):
        """Empty bar data should fail open with RS = 1.0."""
        from scan_engine import compute_sector_relative_strength

        mock_client = MagicMock()
        import pandas as pd

        mock_bars_result = MagicMock()
        mock_bars_result.df = pd.DataFrame()
        mock_client.get_stock_bars.return_value = mock_bars_result

        result = compute_sector_relative_strength(
            mock_client,
            sector_etfs={"Information Technology": "XLK"},
            lookback_days=20,
        )

        assert result["Information Technology"] == 1.0

    def test_exception_returns_1(self):
        """API exception should fail open with RS = 1.0."""
        from scan_engine import compute_sector_relative_strength

        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = Exception("API error")

        result = compute_sector_relative_strength(
            mock_client,
            sector_etfs={"Information Technology": "XLK"},
            lookback_days=20,
        )

        assert result["Information Technology"] == 1.0

    def test_empty_sector_etfs(self):
        """Empty sector ETF dict should return empty dict."""
        from scan_engine import compute_sector_relative_strength

        mock_client = MagicMock()
        result = compute_sector_relative_strength(
            mock_client, sector_etfs={}, lookback_days=20,
        )
        assert result == {}


class TestCompositeRankSectorWeight:
    """composite_rank with sector_rs_weight=0 should produce unchanged score."""

    def test_zero_weight_unchanged(self):
        from analytics.cross_sectional import composite_rank

        base = composite_rank(1.0, 0.5, 0.8)
        with_sector = composite_rank(1.0, 0.5, 0.8, sector_rs_z=2.0, sector_rs_weight=0.0)
        assert base == with_sector

    def test_positive_weight_adds(self):
        from analytics.cross_sectional import composite_rank

        base = composite_rank(1.0, 0.5, 0.8)
        with_sector = composite_rank(1.0, 0.5, 0.8, sector_rs_z=2.0, sector_rs_weight=0.2)
        assert with_sector > base
