"""Tests for universe/corporate_actions.py — splits, delistings, price adjustment."""

import pandas as pd
import pytest

from universe.corporate_actions import (
    CorporateAction,
    adjust_prices_for_splits,
    get_delistings,
    load_corporate_actions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(ticker: str, rows: list[tuple[str, float, float, float, float, int]]) -> pd.DataFrame:
    """Create an OHLCV DataFrame from (date, O, H, L, C, V) tuples."""
    records = []
    for date, o, h, l, c, v in rows:
        records.append({"Ticker": ticker, "Date": date, "Open": o, "High": h, "Low": l, "Close": c, "Volume": v})
    return pd.DataFrame(records)


def _write_actions_csv(path, rows: list[tuple[str, str, str, str, str]]):
    """Write a corporate actions CSV with header."""
    lines = ["symbol,action_type,effective_date,ratio,acquirer"]
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# load_corporate_actions
# ---------------------------------------------------------------------------

class TestLoadCorporateActions:
    def test_load_from_csv(self, tmp_path):
        csv_path = tmp_path / "actions.csv"
        _write_actions_csv(csv_path, [
            ("AAPL", "split", "2024-06-10", "4.0", ""),
            ("XYZ", "delisting", "2024-03-01", "", ""),
            ("FOO", "merger", "2024-07-01", "", "BAR"),
        ])

        actions = load_corporate_actions(csv_path)
        assert len(actions) == 3

        assert actions[0].symbol == "AAPL"
        assert actions[0].action_type == "split"
        assert actions[0].ratio == 4.0
        assert actions[0].acquirer is None

        assert actions[1].action_type == "delisting"
        assert actions[1].ratio is None

        assert actions[2].acquirer == "BAR"

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_corporate_actions(tmp_path / "nonexistent.csv") == []

    def test_frozen_dataclass(self):
        a = CorporateAction("AAPL", "split", "2024-01-01", 2.0)
        with pytest.raises(AttributeError):
            a.symbol = "MSFT"


# ---------------------------------------------------------------------------
# adjust_prices_for_splits
# ---------------------------------------------------------------------------

class TestAdjustPricesForSplits:
    def test_2_for_1_split(self):
        """Price 100 with 2-for-1 split -> pre-split prices become 50."""
        df = _make_ohlcv("AAPL", [
            ("2024-01-01", 100.0, 110.0, 90.0, 100.0, 1000),
            ("2024-01-02", 102.0, 112.0, 92.0, 102.0, 1000),
            # Split happens on 2024-01-03
            ("2024-01-03", 51.0, 56.0, 46.0, 51.0, 2000),
            ("2024-01-04", 52.0, 57.0, 47.0, 52.0, 2000),
        ])

        actions = [CorporateAction("AAPL", "split", "2024-01-03", 2.0)]
        adjusted = adjust_prices_for_splits(df, actions)

        # Pre-split rows (Jan 1-2) should have prices halved
        assert adjusted.iloc[0]["Close"] == pytest.approx(50.0)
        assert adjusted.iloc[0]["Open"] == pytest.approx(50.0)
        assert adjusted.iloc[0]["High"] == pytest.approx(55.0)
        assert adjusted.iloc[0]["Low"] == pytest.approx(45.0)
        assert adjusted.iloc[1]["Close"] == pytest.approx(51.0)

        # Post-split rows (Jan 3-4) unchanged
        assert adjusted.iloc[2]["Close"] == pytest.approx(51.0)
        assert adjusted.iloc[3]["Close"] == pytest.approx(52.0)

    def test_volume_adjusted(self):
        """1000 shares pre-split -> 2000 shares after 2-for-1 adjustment."""
        df = _make_ohlcv("AAPL", [
            ("2024-01-01", 100.0, 110.0, 90.0, 100.0, 1000),
            ("2024-01-03", 51.0, 56.0, 46.0, 51.0, 2000),
        ])
        actions = [CorporateAction("AAPL", "split", "2024-01-03", 2.0)]
        adjusted = adjust_prices_for_splits(df, actions)

        assert adjusted.iloc[0]["Volume"] == pytest.approx(2000)  # 1000 * 2
        assert adjusted.iloc[1]["Volume"] == pytest.approx(2000)  # unchanged

    def test_multiple_splits_same_symbol(self):
        """Two splits on same symbol applied correctly."""
        df = _make_ohlcv("TSLA", [
            ("2024-01-01", 900.0, 950.0, 850.0, 900.0, 500),
            ("2024-03-01", 300.0, 320.0, 280.0, 300.0, 1500),
            ("2024-06-01", 100.0, 110.0, 90.0, 100.0, 4500),
        ])
        actions = [
            CorporateAction("TSLA", "split", "2024-02-01", 3.0),  # 3-for-1
            CorporateAction("TSLA", "split", "2024-05-01", 3.0),  # another 3-for-1
        ]
        adjusted = adjust_prices_for_splits(df, actions)

        # Row 0 (Jan 1): affected by both splits -> 900 * (1/3) * (1/3) = 100
        assert adjusted.iloc[0]["Close"] == pytest.approx(100.0)
        assert adjusted.iloc[0]["Volume"] == pytest.approx(500 * 3 * 3)

        # Row 1 (Mar 1): only affected by second split -> 300 * (1/3) = 100
        assert adjusted.iloc[1]["Close"] == pytest.approx(100.0)
        assert adjusted.iloc[1]["Volume"] == pytest.approx(1500 * 3)

        # Row 2 (Jun 1): after both splits -> unchanged
        assert adjusted.iloc[2]["Close"] == pytest.approx(100.0)
        assert adjusted.iloc[2]["Volume"] == pytest.approx(4500)

    def test_does_not_modify_original(self):
        """Returns new DataFrame, original unchanged."""
        df = _make_ohlcv("AAPL", [
            ("2024-01-01", 100.0, 110.0, 90.0, 100.0, 1000),
        ])
        original_close = df.iloc[0]["Close"]
        actions = [CorporateAction("AAPL", "split", "2024-06-01", 2.0)]
        _ = adjust_prices_for_splits(df, actions)
        assert df.iloc[0]["Close"] == original_close

    def test_empty_actions(self):
        df = _make_ohlcv("AAPL", [("2024-01-01", 100.0, 110.0, 90.0, 100.0, 1000)])
        result = adjust_prices_for_splits(df, [])
        assert result.iloc[0]["Close"] == pytest.approx(100.0)

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"])
        actions = [CorporateAction("AAPL", "split", "2024-01-01", 2.0)]
        result = adjust_prices_for_splits(df, actions)
        assert result.empty

    def test_non_split_actions_ignored(self):
        """Merger and delisting actions don't affect prices."""
        df = _make_ohlcv("XYZ", [("2024-01-01", 100.0, 110.0, 90.0, 100.0, 1000)])
        actions = [
            CorporateAction("XYZ", "merger", "2024-06-01", None, "BIGCO"),
            CorporateAction("XYZ", "delisting", "2024-06-01", None),
        ]
        result = adjust_prices_for_splits(df, actions)
        assert result.iloc[0]["Close"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# get_delistings
# ---------------------------------------------------------------------------

class TestGetDelistings:
    def test_returns_delisted_symbols(self):
        actions = [
            CorporateAction("AAPL", "split", "2024-01-01", 2.0),
            CorporateAction("DEAD", "delisting", "2024-03-01", None),
            CorporateAction("GONE", "delisting", "2024-06-01", None),
        ]
        result = get_delistings(actions)
        assert set(result) == {"DEAD", "GONE"}

    def test_as_of_date_filter(self):
        actions = [
            CorporateAction("EARLY", "delisting", "2024-01-01", None),
            CorporateAction("LATE", "delisting", "2024-12-01", None),
        ]
        result = get_delistings(actions, as_of_date="2024-06-01")
        assert result == ["EARLY"]

    def test_empty_actions(self):
        assert get_delistings([]) == []

    def test_no_delistings(self):
        actions = [CorporateAction("AAPL", "split", "2024-01-01", 2.0)]
        assert get_delistings(actions) == []
