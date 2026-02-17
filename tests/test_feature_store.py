"""Tests for feature_store: schemas, writers, readers, store, versioning."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from feature_store.readers import read_feature_meta, read_features
from feature_store.schemas import AVWAPFeatures, RegimeFeatures, TrendFeatures
from feature_store.store import FeatureStore
from feature_store.versioning import (
    get_current_schema_version,
    get_store_path,
    list_available_dates,
)
from feature_store.writers import write_feature_partition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trend_df(symbols: list[str] | None = None) -> pd.DataFrame:
    symbols = symbols or ["AAPL", "MSFT", "GOOG"]
    rows = [
        TrendFeatures(
            symbol=s,
            trend_score=7.5,
            sma50_slope=0.02,
            adx=30.0,
            vol_ratio=1.2,
            atr_pct=2.5,
        ).to_dict()
        for s in symbols
    ]
    return pd.DataFrame(rows)


def _regime_df() -> pd.DataFrame:
    row = RegimeFeatures(
        spy_vol=0.18,
        spy_drawdown=-0.03,
        spy_trend=1.0,
        breadth=0.55,
        regime_label="RISK_ON",
    ).to_dict()
    return pd.DataFrame([row])


def _avwap_df(symbols: list[str] | None = None) -> pd.DataFrame:
    symbols = symbols or ["AAPL", "TSLA"]
    rows = [
        AVWAPFeatures(
            symbol=s,
            anchor="2025-01-10",
            avwap_slope=0.015,
            dist_pct=2.1,
            setup_vwap_control="above",
            setup_avwap_control="above",
            setup_extension_state="normal",
            setup_structure_state="uptrend",
        ).to_dict()
        for s in symbols
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_trend_roundtrip(self):
        t = TrendFeatures(symbol="AAPL", trend_score=8.0, sma50_slope=0.01, adx=25.0, vol_ratio=1.1, atr_pct=3.0)
        d = t.to_dict()
        assert d["symbol"] == "AAPL"
        assert "SCHEMA_VERSION" not in d
        t2 = TrendFeatures.from_dict(d)
        assert t2 == t

    def test_regime_roundtrip(self):
        r = RegimeFeatures(spy_vol=0.2, spy_drawdown=-0.05, spy_trend=0.0, breadth=0.4, regime_label="RISK_OFF")
        d = r.to_dict()
        r2 = RegimeFeatures.from_dict(d)
        assert r2 == r

    def test_avwap_roundtrip(self):
        a = AVWAPFeatures(
            symbol="TSLA",
            anchor="2025-01-15",
            avwap_slope=0.02,
            dist_pct=1.5,
            setup_vwap_control="above",
            setup_avwap_control="below",
            setup_extension_state="extended",
            setup_structure_state="consolidation",
        )
        d = a.to_dict()
        a2 = AVWAPFeatures.from_dict(d)
        assert a2 == a

    def test_from_dict_ignores_extra_keys(self):
        d = {"symbol": "X", "trend_score": 1.0, "bogus_field": 999}
        t = TrendFeatures.from_dict(d)
        assert t.symbol == "X"
        assert t.trend_score == 1.0

    def test_schema_version_attribute(self):
        assert TrendFeatures.SCHEMA_VERSION == 1
        assert RegimeFeatures.SCHEMA_VERSION == 1
        assert AVWAPFeatures.SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# Write + read roundtrip
# ---------------------------------------------------------------------------


class TestWriteReadRoundtrip:
    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_trend_roundtrip(self, _mock_sha, tmp_path: Path):
        df = _trend_df()
        write_feature_partition(tmp_path, "2025-06-01", "trend_features", df)
        result = read_features(tmp_path, "trend_features", "2025-06-01")
        pd.testing.assert_frame_equal(result.reset_index(drop=True), df.reset_index(drop=True))

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_regime_roundtrip(self, _mock_sha, tmp_path: Path):
        df = _regime_df()
        write_feature_partition(tmp_path, "2025-06-01", "regime_features", df)
        result = read_features(tmp_path, "regime_features", "2025-06-01")
        pd.testing.assert_frame_equal(result.reset_index(drop=True), df.reset_index(drop=True))

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_avwap_roundtrip(self, _mock_sha, tmp_path: Path):
        df = _avwap_df()
        write_feature_partition(tmp_path, "2025-06-01", "avwap_features", df)
        result = read_features(tmp_path, "avwap_features", "2025-06-01")
        pd.testing.assert_frame_equal(result.reset_index(drop=True), df.reset_index(drop=True))


# ---------------------------------------------------------------------------
# Point-in-time correctness
# ---------------------------------------------------------------------------


class TestPointInTime:
    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_never_returns_future_data(self, _mock_sha, tmp_path: Path):
        """Write D1, D2, D3. Read as-of D2 => must return D2, NOT D3."""
        for d in ["2025-01-10", "2025-01-20", "2025-01-30"]:
            write_feature_partition(tmp_path, d, "trend_features", _trend_df([d]))

        result = read_features(tmp_path, "trend_features", "2025-01-20")
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "2025-01-20"

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_returns_latest_on_or_before(self, _mock_sha, tmp_path: Path):
        """Read as-of a date between D1 and D2 => returns D1."""
        write_feature_partition(tmp_path, "2025-01-10", "trend_features", _trend_df(["D1"]))
        write_feature_partition(tmp_path, "2025-01-20", "trend_features", _trend_df(["D2"]))

        result = read_features(tmp_path, "trend_features", "2025-01-15")
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "D1"

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_returns_exact_date(self, _mock_sha, tmp_path: Path):
        write_feature_partition(tmp_path, "2025-01-10", "trend_features", _trend_df(["EXACT"]))
        result = read_features(tmp_path, "trend_features", "2025-01-10")
        assert result.iloc[0]["symbol"] == "EXACT"

    def test_no_data_before_request(self, tmp_path: Path):
        """Reading from a date before any partition => empty."""
        result = read_features(tmp_path, "trend_features", "2020-01-01")
        assert result.empty


# ---------------------------------------------------------------------------
# Empty store
# ---------------------------------------------------------------------------


class TestEmptyStore:
    def test_read_empty_returns_empty_df(self, tmp_path: Path):
        result = read_features(tmp_path, "trend_features", "2025-06-01")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_read_meta_empty_returns_empty_dict(self, tmp_path: Path):
        result = read_feature_meta(tmp_path, "trend_features", "2025-06-01")
        assert result == {}

    def test_list_dates_empty(self, tmp_path: Path):
        assert list_available_dates(tmp_path, "trend_features") == []


# ---------------------------------------------------------------------------
# Atomic write safety
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_no_tmp_files_after_success(self, _mock_sha, tmp_path: Path):
        write_feature_partition(tmp_path, "2025-06-01", "trend_features", _trend_df())
        partition = tmp_path / "v1" / "2025-06-01"
        tmp_files = list(partition.glob("*.tmp"))
        assert tmp_files == [], f"Leftover tmp files: {tmp_files}"

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_failed_write_leaves_no_partial_parquet(self, _mock_sha, tmp_path: Path):
        """Simulate a write failure — no .parquet should be left."""
        bad_df = "not a dataframe"
        with pytest.raises(Exception):
            write_feature_partition(tmp_path, "2025-06-01", "trend_features", bad_df)

        partition = tmp_path / "v1" / "2025-06-01"
        parquet_files = list(partition.glob("*.parquet")) if partition.exists() else []
        assert parquet_files == []


# ---------------------------------------------------------------------------
# Meta / provenance
# ---------------------------------------------------------------------------


class TestMeta:
    @patch("feature_store.writers.git_sha", return_value="deadbeef")
    def test_meta_contains_provenance(self, _mock_sha, tmp_path: Path):
        write_feature_partition(
            tmp_path,
            "2025-06-01",
            "trend_features",
            _trend_df(),
            meta={"run_id": "run-42"},
        )
        meta = read_feature_meta(tmp_path, "trend_features", "2025-06-01")
        assert meta["git_sha"] == "deadbeef"
        assert meta["schema_version"] == 1
        assert meta["run_id"] == "run-42"
        assert meta["feature_type"] == "trend_features"
        assert meta["date"] == "2025-06-01"
        assert meta["row_count"] == 3

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_meta_point_in_time(self, _mock_sha, tmp_path: Path):
        """Meta lookup obeys the same point-in-time rule as features."""
        write_feature_partition(tmp_path, "2025-01-10", "trend_features", _trend_df(), meta={"run_id": "r1"})
        write_feature_partition(tmp_path, "2025-01-20", "trend_features", _trend_df(), meta={"run_id": "r2"})

        meta = read_feature_meta(tmp_path, "trend_features", "2025-01-15")
        assert meta["run_id"] == "r1"


# ---------------------------------------------------------------------------
# Versioning utilities
# ---------------------------------------------------------------------------


class TestVersioning:
    def test_current_schema_version(self):
        assert get_current_schema_version() == 1

    def test_store_path_default(self, tmp_path: Path):
        p = get_store_path(tmp_path)
        assert p == tmp_path / "v1"

    def test_store_path_explicit(self, tmp_path: Path):
        p = get_store_path(tmp_path, version=2)
        assert p == tmp_path / "v2"

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_list_available_dates(self, _mock_sha, tmp_path: Path):
        for d in ["2025-01-10", "2025-01-20", "2025-01-15"]:
            write_feature_partition(tmp_path, d, "trend_features", _trend_df())
        dates = list_available_dates(tmp_path, "trend_features")
        assert dates == ["2025-01-10", "2025-01-15", "2025-01-20"]


# ---------------------------------------------------------------------------
# FeatureStore facade
# ---------------------------------------------------------------------------


class TestFeatureStoreFacade:
    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_write_and_read(self, _mock_sha, tmp_path: Path):
        store = FeatureStore(base_dir=tmp_path)
        df = _trend_df()
        store.write("2025-06-01", "trend_features", df)
        result = store.read("trend_features", "2025-06-01")
        pd.testing.assert_frame_equal(result.reset_index(drop=True), df.reset_index(drop=True))

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_read_meta(self, _mock_sha, tmp_path: Path):
        store = FeatureStore(base_dir=tmp_path)
        store.write("2025-06-01", "trend_features", _trend_df(), meta={"run_id": "test"})
        meta = store.read_meta("trend_features", "2025-06-01")
        assert meta["run_id"] == "test"

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_available_dates(self, _mock_sha, tmp_path: Path):
        store = FeatureStore(base_dir=tmp_path)
        store.write("2025-01-10", "trend_features", _trend_df())
        store.write("2025-01-20", "trend_features", _trend_df())
        assert store.available_dates("trend_features") == ["2025-01-10", "2025-01-20"]

    @patch("feature_store.writers.git_sha", return_value="abc123")
    def test_point_in_time_via_facade(self, _mock_sha, tmp_path: Path):
        store = FeatureStore(base_dir=tmp_path)
        store.write("2025-01-10", "trend_features", _trend_df(["D1"]))
        store.write("2025-01-20", "trend_features", _trend_df(["D2"]))
        store.write("2025-01-30", "trend_features", _trend_df(["D3"]))

        result = store.read("trend_features", "2025-01-25")
        assert result.iloc[0]["symbol"] == "D2"

    def test_empty_store(self, tmp_path: Path):
        store = FeatureStore(base_dir=tmp_path)
        assert store.read("trend_features", "2025-01-01").empty
        assert store.read_meta("trend_features", "2025-01-01") == {}
        assert store.available_dates("trend_features") == []
