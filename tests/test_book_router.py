from __future__ import annotations

import builtins
import sys

import pytest

from execution_v2 import book_ids, book_router


def test_schwab_selection_does_not_import_alpaca(monkeypatch) -> None:
    for name in list(sys.modules):
        if name == "alpaca" or name.startswith("alpaca."):
            sys.modules.pop(name, None)

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("alpaca"):
            raise AssertionError("alpaca import attempted")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(NotImplementedError):
        book_router.select_trading_client(book_ids.SCHWAB_401K_MANUAL)
