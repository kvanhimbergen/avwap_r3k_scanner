"""Combinatorial Purged Cross-Validation (CPCV).

Implements the Lopez de Prado framework for generating walk-forward splits
that combat overfitting through combinatorial test/train partitioning with
purge and embargo windows to prevent information leakage.
"""

from __future__ import annotations

import itertools
from typing import Sequence


def generate_cpcv_splits(
    trading_days: Sequence,
    n_groups: int,
    k_test_groups: int,
    purge_days: int = 5,
    embargo_days: int = 3,
) -> list[dict]:
    """Generate all C(n_groups, k_test_groups) combinatorial purged CV splits.

    Parameters
    ----------
    trading_days : sequence
        Ordered sequence of trading day identifiers (dates, timestamps, etc.).
    n_groups : int
        Number of groups to partition trading_days into (>= 2).
    k_test_groups : int
        Number of groups to select as test set per split (>= 1, < n_groups).
    purge_days : int
        Days to remove from the end of each train segment that borders a test segment.
    embargo_days : int
        Days to remove from the start of each test segment.

    Returns
    -------
    list[dict]
        Each dict has "train_dates" and "test_dates" keys with lists of trading days.
    """
    if n_groups < 2:
        raise ValueError(f"n_groups must be >= 2, got {n_groups}")
    if k_test_groups < 1:
        raise ValueError(f"k_test_groups must be >= 1, got {k_test_groups}")
    if k_test_groups >= n_groups:
        raise ValueError(
            f"k_test_groups must be < n_groups, got k={k_test_groups} n={n_groups}"
        )

    days = list(trading_days)
    n = len(days)
    if n == 0:
        return []

    # Split into n_groups roughly equal groups
    group_size, remainder = divmod(n, n_groups)
    groups: list[list] = []
    start = 0
    for i in range(n_groups):
        end = start + group_size + (1 if i < remainder else 0)
        groups.append(days[start:end])
        start = end

    splits = []
    for test_combo in itertools.combinations(range(n_groups), k_test_groups):
        test_indices = set(test_combo)
        train_indices = [i for i in range(n_groups) if i not in test_indices]

        # Build raw test and train date sets
        raw_test = []
        for i in test_indices:
            raw_test.extend(groups[i])

        raw_train = []
        for i in train_indices:
            raw_train.extend(groups[i])

        # Apply purge: remove purge_days from end of each train group that borders a test group
        purged_train = list(raw_train)
        if purge_days > 0:
            for train_idx in train_indices:
                group_days = groups[train_idx]
                if not group_days:
                    continue

                # If the next group is a test group, purge from end of this train group
                if (train_idx + 1) in test_indices:
                    days_to_remove = set(group_days[-purge_days:])
                    purged_train = [d for d in purged_train if d not in days_to_remove]

                # If the previous group is a test group, purge from start of this train group
                if (train_idx - 1) in test_indices:
                    days_to_remove = set(group_days[:purge_days])
                    purged_train = [d for d in purged_train if d not in days_to_remove]

        # Apply embargo: remove embargo_days from start of each test group
        embargoed_test = list(raw_test)
        if embargo_days > 0:
            for i in sorted(test_indices):
                group_days = groups[i]
                if not group_days:
                    continue
                days_to_remove = set(group_days[:embargo_days])
                embargoed_test = [d for d in embargoed_test if d not in days_to_remove]

        splits.append({
            "train_dates": sorted(purged_train),
            "test_dates": sorted(embargoed_test),
        })

    return splits
