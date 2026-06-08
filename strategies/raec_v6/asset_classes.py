"""Asset-class taxonomy loader.

Reads strategies/raec_v6/asset_classes.yaml and exposes:
- ASSET_CLASSES: dict[str, tuple[str, ...]]   class -> symbols
- SYMBOL_TO_CLASS: dict[str, str]              symbol -> class
- ALL_SYMBOLS: frozenset[str]                  every symbol in the taxonomy
- get_asset_class(symbol) -> str               raises KeyError if unknown
- get_symbols_in_class(cls) -> tuple[str, ...] raises KeyError if unknown

Loaded once at import time; symbols are uppercased.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml


_TAXONOMY_PATH = Path(__file__).parent / "asset_classes.yaml"


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    with _TAXONOMY_PATH.open() as f:
        raw: dict[str, list[str]] = yaml.safe_load(f)
    classes: dict[str, tuple[str, ...]] = {}
    symbol_to_class: dict[str, str] = {}
    for cls, syms in raw.items():
        cls_norm = str(cls)
        sym_upper = tuple(str(s).upper() for s in syms)
        if cls_norm in classes:
            raise ValueError(f"Duplicate asset class in taxonomy: {cls_norm}")
        classes[cls_norm] = sym_upper
        for s in sym_upper:
            if s in symbol_to_class:
                raise ValueError(
                    f"Symbol {s} appears in multiple classes: "
                    f"{symbol_to_class[s]} and {cls_norm}"
                )
            symbol_to_class[s] = cls_norm
    return classes, symbol_to_class


ASSET_CLASSES: dict[str, tuple[str, ...]] = _load()[0]
SYMBOL_TO_CLASS: dict[str, str] = _load()[1]
ALL_SYMBOLS: frozenset[str] = frozenset(SYMBOL_TO_CLASS)


def get_asset_class(symbol: str) -> str:
    sym = symbol.upper()
    if sym not in SYMBOL_TO_CLASS:
        raise KeyError(f"Symbol {sym!r} not in v6 asset taxonomy")
    return SYMBOL_TO_CLASS[sym]


def get_symbols_in_class(asset_class: str) -> tuple[str, ...]:
    if asset_class not in ASSET_CLASSES:
        raise KeyError(f"Asset class {asset_class!r} not in v6 taxonomy")
    return ASSET_CLASSES[asset_class]
