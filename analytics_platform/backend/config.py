from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_dir: Path
    db_path: Path
    refresh_seconds: int = 60
    enable_scheduler: bool = True

    @property
    def ledger_dir(self) -> Path:
        return self.repo_root / "ledger"

    @property
    def state_dir(self) -> Path:
        return self.repo_root / "state"

    @property
    def backtests_dir(self) -> Path:
        return self.repo_root / "backtests"

    @property
    def frontend_dist_dir(self) -> Path:
        return self.repo_root / "analytics_platform" / "frontend" / "dist"

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "Settings":
        root = repo_root or Path(__file__).resolve().parents[2]
        data_dir = root / "analytics_platform" / "data"
        db_path = Path(os.getenv("ANALYTICS_DB_PATH", str(data_dir / "analytics.duckdb"))).resolve()
        refresh_seconds = int(os.getenv("ANALYTICS_REFRESH_SECONDS", "60"))
        enable_scheduler = os.getenv("ANALYTICS_ENABLE_SCHEDULER", "1").strip() == "1"
        return cls(
            repo_root=root,
            data_dir=data_dir,
            db_path=db_path,
            refresh_seconds=max(15, refresh_seconds),
            enable_scheduler=enable_scheduler,
        )
