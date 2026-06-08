"""Tests for asset-class taxonomy loader."""

from __future__ import annotations

import pytest

from strategies.raec_v6 import asset_classes as ac


def test_taxonomy_loads() -> None:
    assert len(ac.ASSET_CLASSES) > 10
    assert len(ac.ALL_SYMBOLS) > 50


def test_each_symbol_in_exactly_one_class() -> None:
    seen: set[str] = set()
    for syms in ac.ASSET_CLASSES.values():
        for s in syms:
            assert s not in seen, f"{s} appears in multiple classes"
            seen.add(s)
    assert seen == ac.ALL_SYMBOLS


def test_lookup_normalizes_case() -> None:
    assert ac.get_asset_class("ibit") == "crypto"
    assert ac.get_asset_class("IBIT") == "crypto"


def test_unknown_symbol_raises() -> None:
    with pytest.raises(KeyError):
        ac.get_asset_class("FAKE_SYM_999")


def test_unknown_asset_class_raises() -> None:
    with pytest.raises(KeyError):
        ac.get_symbols_in_class("imaginary_class")


def test_critical_symbols_present() -> None:
    # Smoke check the universe the v6 redesign needs across asset classes.
    must_have = {
        "SPY": "equity_us_broad",
        "TQQQ": "equity_us_lev",
        "TLT": "bond_long",
        "GLD": "metal",
        "IBIT": "crypto",
        "VIXY": "vol_long",
        "PSQ": "inverse_equity",
        "UUP": "currency_dollar",
        "PDBC": "commodity_broad",
    }
    for sym, cls in must_have.items():
        assert ac.get_asset_class(sym) == cls
