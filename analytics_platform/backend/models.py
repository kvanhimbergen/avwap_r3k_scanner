from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class BuildResult:
    as_of_utc: str
    data_version: str
    source_window: dict[str, Any]
    warnings: list[str]
    row_counts: dict[str, int]


@dataclass(frozen=True)
class ApiEnvelope:
    as_of_utc: str
    source_window: dict[str, Any]
    data_version: str
    warnings: list[str]
    data: Any

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
