from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import contextlib
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from analytics_platform.backend.api import queries
from analytics_platform.backend.config import Settings
from analytics_platform.backend.db import connect_ro
from analytics_platform.backend.models import ApiEnvelope, BuildResult, utc_now_iso
from analytics_platform.backend.readmodels.build_readmodels import build_readmodels


class AnalyticsRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.build_result = BuildResult(
            as_of_utc=utc_now_iso(),
            data_version="bootstrap",
            source_window={"date_min": None, "date_max": None},
            warnings=["read models not built yet"],
            row_counts={},
        )
        self.refresh_error: str | None = None
        self.refresh_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def refresh_once(self) -> None:
        async with self._lock:
            try:
                result = await asyncio.to_thread(build_readmodels, self.settings)
            except Exception as exc:  # noqa: BLE001 - fail-open service
                self.refresh_error = str(exc)
                return
            self.build_result = result
            self.refresh_error = None

    async def refresh_loop(self) -> None:
        while True:
            await self.refresh_once()
            await asyncio.sleep(self.settings.refresh_seconds)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    runtime: AnalyticsRuntime = app.state.runtime
    await runtime.refresh_once()
    if runtime.settings.enable_scheduler:
        runtime.refresh_task = asyncio.create_task(runtime.refresh_loop())
    try:
        yield
    finally:
        if runtime.refresh_task is not None:
            runtime.refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runtime.refresh_task


def _envelope(runtime: AnalyticsRuntime, data: dict | list) -> dict:
    return ApiEnvelope(
        as_of_utc=runtime.build_result.as_of_utc,
        source_window=runtime.build_result.source_window,
        data_version=runtime.build_result.data_version,
        warnings=list(runtime.build_result.warnings),
        data=data,
    ).to_dict()


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    app = FastAPI(title="Strategy Analytics Platform", version="1.0.0", lifespan=_lifespan)
    app.state.runtime = AnalyticsRuntime(cfg)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8788", "http://127.0.0.1:8788", "*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        stale_source_count = 0
        try:
            with connect_ro(runtime.settings.db_path) as conn:
                stale_source_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM freshness_health
                        WHERE parse_status <> 'ok' OR file_count = 0
                        """
                    ).fetchone()[0]
                )
        except Exception:
            stale_source_count = 0

        lag_seconds = 0.0
        try:
            refreshed_at = datetime.fromisoformat(runtime.build_result.as_of_utc)
            lag_seconds = max(0.0, (datetime.now(timezone.utc) - refreshed_at).total_seconds())
        except Exception:
            lag_seconds = 0.0

        payload = {
            "status": "ok" if runtime.refresh_error is None else "degraded",
            "refresh_error": runtime.refresh_error,
            "refresh_interval_seconds": runtime.settings.refresh_seconds,
            "readmodel_lag_seconds": round(lag_seconds, 3),
            "stale_source_count": stale_source_count,
            "row_counts": runtime.build_result.row_counts,
            "scheduler_enabled": runtime.settings.enable_scheduler,
        }
        return _envelope(runtime, payload)

    @app.get("/api/v1/freshness")
    def freshness() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = {"rows": queries.get_freshness(conn)}
        return _envelope(runtime, payload)

    @app.get("/api/v1/overview")
    def overview(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_overview(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/strategies/compare")
    def strategies_compare(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_strategies_compare(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/decisions/timeseries")
    def decisions_timeseries(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        granularity: str = Query(default="day"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_decisions_timeseries(conn, start, end, granularity)
        return _envelope(runtime, payload)

    @app.get("/api/v1/signals/s2")
    def signals_s2(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        symbol: str | None = None,
        eligible: bool | None = None,
        selected: bool | None = None,
        reason_code: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_s2_signals(
                conn,
                date=date,
                symbol=symbol,
                eligible=eligible,
                selected=selected,
                reason_code=reason_code,
                limit=limit,
            )
        return _envelope(runtime, payload)

    @app.get("/api/v1/risk/controls")
    def risk_controls(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_risk_controls(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/backtests/runs")
    def backtest_runs() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = {"runs": queries.list_backtest_runs(conn)}
        return _envelope(runtime, payload)

    @app.get("/api/v1/backtests/runs/{run_id}")
    def backtest_run(run_id: str) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_backtest_run(conn, run_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
        return _envelope(runtime, payload)

    @app.get("/api/v1/raec/dashboard")
    def raec_dashboard(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_raec_dashboard(conn, start, end, strategy_id)
        return _envelope(runtime, payload)

    @app.get("/api/v1/journal")
    def journal(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_journal(
                conn, start=start, end=end, strategy_id=strategy_id,
                symbol=symbol, side=side, limit=limit,
            )
        return _envelope(runtime, payload)

    @app.get("/api/v1/raec/readiness")
    def raec_readiness() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_raec_readiness(conn, runtime.settings.repo_root)
        return _envelope(runtime, payload)

    @app.get("/api/v1/pnl")
    def pnl(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_pnl(conn, start, end, strategy_id)
        return _envelope(runtime, payload)

    @app.get("/api/v1/exports/{dataset}.csv")
    def export_dataset(
        dataset: str,
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=10000, ge=1, le=100000),
    ) -> Response:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            try:
                filename, csv_data = queries.export_dataset_csv(
                    conn,
                    dataset=dataset,
                    start=start,
                    end=end,
                    limit=limit,
                )
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=f"unknown dataset: {dataset}") from exc
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/")
    def root() -> JSONResponse:
        runtime: AnalyticsRuntime = app.state.runtime
        return JSONResponse(
            {
                "service": "analytics-platform",
                "api": "/api/v1",
                "frontend": "/app",
                "as_of_utc": runtime.build_result.as_of_utc,
            }
        )

    dist_dir = cfg.frontend_dist_dir
    if dist_dir.exists():
        app.mount("/app", StaticFiles(directory=str(dist_dir), html=True), name="app")

    return app
