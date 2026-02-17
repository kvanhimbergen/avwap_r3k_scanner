from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect_rw(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    ensure_parent_dir(path)
    conn = duckdb.connect(str(path))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def connect_ro(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(str(path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()
