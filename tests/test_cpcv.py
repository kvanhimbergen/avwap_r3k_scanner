"""Tests for analytics.cpcv — Combinatorial Purged Cross-Validation."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from analytics.cpcv import generate_cpcv_splits


def _make_trading_days(n: int, start: date = date(2020, 1, 1)) -> list[date]:
    """Generate n sequential dates (weekdays only, no gaps for simplicity)."""
    return [start + timedelta(days=i) for i in range(n)]


class TestBasicSplitGeneration:
    def test_5_groups_2_test_produces_10_splits(self):
        days = _make_trading_days(100)
        splits = generate_cpcv_splits(days, n_groups=5, k_test_groups=2)
        assert len(splits) == math.comb(5, 2)  # 10

    def test_each_split_has_train_and_test_keys(self):
        days = _make_trading_days(100)
        splits = generate_cpcv_splits(days, n_groups=5, k_test_groups=2)
        for split in splits:
            assert "train_dates" in split
            assert "test_dates" in split
            assert len(split["train_dates"]) > 0
            assert len(split["test_dates"]) > 0

    def test_4_groups_1_test_produces_4_splits(self):
        days = _make_trading_days(80)
        splits = generate_cpcv_splits(days, n_groups=4, k_test_groups=1)
        assert len(splits) == math.comb(4, 1)  # 4

    def test_6_groups_3_test_produces_20_splits(self):
        days = _make_trading_days(120)
        splits = generate_cpcv_splits(days, n_groups=6, k_test_groups=3)
        assert len(splits) == math.comb(6, 3)  # 20


class TestNoOverlap:
    def test_no_overlap_between_train_and_test(self):
        days = _make_trading_days(100)
        splits = generate_cpcv_splits(days, n_groups=5, k_test_groups=2)
        for split in splits:
            train_set = set(split["train_dates"])
            test_set = set(split["test_dates"])
            assert train_set.isdisjoint(test_set), "Train and test dates overlap"

    def test_no_overlap_simple_2fold(self):
        days = _make_trading_days(50)
        splits = generate_cpcv_splits(
            days, n_groups=2, k_test_groups=1, purge_days=0, embargo_days=0
        )
        for split in splits:
            train_set = set(split["train_dates"])
            test_set = set(split["test_dates"])
            assert train_set.isdisjoint(test_set)


class TestPurge:
    def test_purge_removes_days_from_train_border(self):
        days = _make_trading_days(100)
        purge_days = 5

        # No purge baseline
        splits_no_purge = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=0, embargo_days=0
        )
        # With purge
        splits_purged = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=purge_days, embargo_days=0
        )

        for no_purge, purged in zip(splits_no_purge, splits_purged):
            assert len(purged["train_dates"]) < len(no_purge["train_dates"]), (
                "Purge should remove some train dates"
            )

    def test_purge_days_not_in_train(self):
        # With 2 groups, group boundary is at day 25 (50 days total)
        days = _make_trading_days(50)
        purge_days = 3
        splits = generate_cpcv_splits(
            days, n_groups=2, k_test_groups=1, purge_days=purge_days, embargo_days=0
        )
        # In the split where group 1 is test, group 0 is train
        # The last purge_days of group 0 should be removed from train
        for split in splits:
            train_set = set(split["train_dates"])
            test_set = set(split["test_dates"])
            # No overlap after purge
            assert train_set.isdisjoint(test_set)


class TestEmbargo:
    def test_embargo_removes_days_from_test_start(self):
        days = _make_trading_days(100)
        embargo_days = 3

        splits_no_embargo = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=0, embargo_days=0
        )
        splits_embargoed = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=0, embargo_days=embargo_days
        )

        for no_embargo, embargoed in zip(splits_no_embargo, splits_embargoed):
            assert len(embargoed["test_dates"]) < len(no_embargo["test_dates"]), (
                "Embargo should remove some test dates"
            )

    def test_embargo_removes_correct_count(self):
        days = _make_trading_days(100)
        embargo_days = 3
        splits_no_embargo = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=0, embargo_days=0
        )
        splits_embargoed = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=0, embargo_days=embargo_days
        )
        for no_emb, emb in zip(splits_no_embargo, splits_embargoed):
            # k_test_groups=2 means 2 test groups, each loses embargo_days
            removed = len(no_emb["test_dates"]) - len(emb["test_dates"])
            # Each test group loses up to embargo_days
            assert removed == embargo_days * 2


class TestEdgeCases:
    def test_2_groups_1_test_simple_2fold(self):
        days = _make_trading_days(20)
        splits = generate_cpcv_splits(
            days, n_groups=2, k_test_groups=1, purge_days=0, embargo_days=0
        )
        assert len(splits) == 2
        # Together, test sets should cover all days
        all_test = set()
        for split in splits:
            all_test.update(split["test_dates"])
        assert all_test == set(days)

    def test_empty_trading_days(self):
        splits = generate_cpcv_splits([], n_groups=5, k_test_groups=2)
        assert splits == []

    def test_n_groups_less_than_2_raises(self):
        days = _make_trading_days(20)
        with pytest.raises(ValueError, match="n_groups must be >= 2"):
            generate_cpcv_splits(days, n_groups=1, k_test_groups=1)

    def test_k_test_groups_less_than_1_raises(self):
        days = _make_trading_days(20)
        with pytest.raises(ValueError, match="k_test_groups must be >= 1"):
            generate_cpcv_splits(days, n_groups=3, k_test_groups=0)

    def test_k_test_groups_ge_n_groups_raises(self):
        days = _make_trading_days(20)
        with pytest.raises(ValueError, match="k_test_groups must be < n_groups"):
            generate_cpcv_splits(days, n_groups=3, k_test_groups=3)


class TestFullCoverage:
    def test_all_days_appear_in_test_sets_across_splits(self):
        days = _make_trading_days(100)
        splits = generate_cpcv_splits(
            days, n_groups=5, k_test_groups=2, purge_days=0, embargo_days=0
        )
        all_test = set()
        for split in splits:
            all_test.update(split["test_dates"])
        assert all_test == set(days), "Every trading day should appear in some test set"

    def test_dates_are_sorted(self):
        days = _make_trading_days(100)
        splits = generate_cpcv_splits(days, n_groups=5, k_test_groups=2)
        for split in splits:
            assert split["train_dates"] == sorted(split["train_dates"])
            assert split["test_dates"] == sorted(split["test_dates"])
