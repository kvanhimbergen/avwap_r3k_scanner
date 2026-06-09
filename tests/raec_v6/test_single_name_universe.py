"""Tests for the single-name universe + sector cap."""

from __future__ import annotations

from strategies.raec_v6.single_name_universe import (
    SECTOR_MAP,
    UNIVERSE,
    apply_sector_cap,
    is_single_name,
)


def test_universe_is_sized_reasonably() -> None:
    assert 25 <= len(UNIVERSE) <= 60


def test_sector_map_covers_universe() -> None:
    for sym in UNIVERSE:
        assert sym in SECTOR_MAP


def test_sector_diversification_in_universe() -> None:
    """Universe itself shouldn't be 100% tech — should span ≥5 sectors."""
    sectors = set(SECTOR_MAP.values())
    assert len(sectors) >= 5


def test_sector_cap_enforces_max_per_sector() -> None:
    """Even if every name in the rank is tech, sector cap keeps it diverse."""
    # All tech names
    tech_only = [s for s, sec in SECTOR_MAP.items() if sec == "Technology"]
    picked = apply_sector_cap(tech_only, top_k=10)
    # Sector cap is 3 → max 3 from tech
    assert len(picked) <= 3


def test_sector_cap_picks_top_k_when_diverse() -> None:
    ranked = ["NVDA", "JPM", "UNH", "TSLA", "PG"]  # 1 each from different sectors
    picked = apply_sector_cap(ranked, top_k=5)
    assert picked == ranked


def test_sector_cap_skips_non_universe_symbols() -> None:
    """Symbols outside the universe (e.g., ETFs) are skipped, not crashed on."""
    ranked = ["SPY", "QQQ", "NVDA", "JPM"]  # SPY/QQQ are not in single-name universe
    picked = apply_sector_cap(ranked, top_k=5)
    assert "SPY" not in picked
    assert "QQQ" not in picked
    assert "NVDA" in picked
    assert "JPM" in picked


def test_is_single_name() -> None:
    assert is_single_name("NVDA") is True
    assert is_single_name("nvda") is True  # case-insensitive
    assert is_single_name("SPY") is False
    assert is_single_name("FAKE") is False
