from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import contextlib
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analytics_platform.backend.api import queries
from analytics_platform.backend.config import Settings
from analytics_platform.backend.db import connect_ro
from analytics_platform.backend.models import ApiEnvelope, BuildResult, utc_now_iso
from analytics_platform.backend.readmodels.build_readmodels import build_readmodels, source_fingerprint
from analytics_platform.backend.trade_log_db import TradeLogStore


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
        self._last_source_fp: str | None = None
        self._consecutive_failures: int = 0

    async def refresh_once(self) -> None:
        async with self._lock:
            try:
                fp = await asyncio.to_thread(source_fingerprint, self.settings)
                if fp == self._last_source_fp:
                    return  # nothing changed on disk
                result = await asyncio.to_thread(build_readmodels, self.settings)
            except Exception as exc:  # noqa: BLE001 - fail-open service
                self.refresh_error = str(exc)
                self._consecutive_failures += 1
                return
            self.build_result = result
            self.refresh_error = None
            self._last_source_fp = fp
            self._consecutive_failures = 0

    async def refresh_loop(self) -> None:
        while True:
            await self.refresh_once()
            # Exponential backoff on consecutive failures (cap at 5 min)
            if self._consecutive_failures > 0:
                delay = min(self.settings.refresh_seconds * (2 ** self._consecutive_failures), 300)
            else:
                delay = self.settings.refresh_seconds
            await asyncio.sleep(delay)


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
        trade_log: TradeLogStore | None = getattr(app.state, "trade_log", None)
        if trade_log is not None:
            trade_log.close()


def _envelope(runtime: AnalyticsRuntime, data: dict | list) -> dict:
    return ApiEnvelope(
        as_of_utc=runtime.build_result.as_of_utc,
        source_window=runtime.build_result.source_window,
        data_version=runtime.build_result.data_version,
        warnings=list(runtime.build_result.warnings),
        data=data,
    ).to_dict()


def _make_api_key_checker(cfg: Settings):
    """Return a FastAPI dependency that validates the API key on mutating endpoints."""
    def _require_api_key(request: Request) -> None:
        if cfg.api_key is None:
            return  # no key configured = auth disabled (local dev)
        token = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if token != cfg.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return _require_api_key


class CreateTradeRequest(BaseModel):
    entry_date: str
    symbol: str
    entry_price: float = Field(gt=0)
    qty: int = Field(gt=0)
    stop_loss: float = Field(gt=0)
    direction: str = Field(default="long", pattern=r"^(long|short)$")
    target_r1: float | None = None
    target_r2: float | None = None
    strategy_source: str | None = None
    scan_date: str | None = None
    notes: str | None = None


class CloseTradeRequest(BaseModel):
    exit_price: float = Field(gt=0)
    exit_date: str | None = None
    exit_reason: str = "manual"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    app = FastAPI(title="Strategy Analytics Platform", version="1.0.0", lifespan=_lifespan)
    app.state.runtime = AnalyticsRuntime(cfg)
    require_api_key = _make_api_key_checker(cfg)
    trade_log_path = cfg.data_dir / "trade_log.duckdb"
    trade_log_path.parent.mkdir(parents=True, exist_ok=True)
    app.state.trade_log = TradeLogStore(trade_log_path)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8788",
            "http://127.0.0.1:8788",
            "https://avwap.vantagedutch.com",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
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
        book_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_raec_dashboard(conn, start, end, strategy_id, book_id)
        return _envelope(runtime, payload)

    _ALPACA_SIDS = {"S1_AVWAP_CORE", "S2_LETF_ORB_AGGRO", "RAEC_401K_V1", "RAEC_401K_V2"}
    _SCHWAB_SIDS = {"RAEC_401K_V3", "RAEC_401K_V4", "RAEC_401K_V5", "RAEC_401K_COORD"}

    @app.get("/api/v1/journal")
    def journal(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
        book_id: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        # Map book_id to strategy_id_in set for journal filtering
        strategy_id_in: set[str] | None = None
        if book_id == "ALPACA_PAPER":
            strategy_id_in = _ALPACA_SIDS
        elif book_id == "SCHWAB_401K_MANUAL":
            strategy_id_in = _SCHWAB_SIDS
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_journal(
                conn, start=start, end=end, strategy_id=strategy_id,
                symbol=symbol, side=side, limit=limit,
                strategy_id_in=strategy_id_in,
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
        book_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_pnl(conn, start, end, strategy_id, book_id)
        return _envelope(runtime, payload)

    @app.get("/api/v1/execution/slippage")
    def execution_slippage(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_slippage_dashboard(conn, start, end, strategy_id)
        return _envelope(runtime, payload)

    @app.get("/api/v1/analytics/trades")
    def analytics_trades(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
        book_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_trade_analytics(conn, start, end, strategy_id, book_id)
        return _envelope(runtime, payload)

    @app.get("/api/v1/portfolio/overview")
    def portfolio_overview(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_portfolio_overview(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/portfolio/positions")
    def portfolio_positions(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_portfolio_positions(conn, date)
        return _envelope(runtime, payload)

    @app.get("/api/v1/portfolio/history")
    def portfolio_history(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_portfolio_history(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/strategies/matrix")
    def strategy_matrix() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_strategy_matrix(conn)
        return _envelope(runtime, payload)

    @app.get("/api/v1/schwab/overview")
    def schwab_overview(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_schwab_overview(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/schwab/trade-instructions")
    def schwab_trade_instructions() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_schwab_trade_instructions(conn)
        return _envelope(runtime, payload)

    @app.get("/api/v1/rebalance/dashboard")
    def rebalance_dashboard() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_rebalance_dashboard(conn, runtime.settings.repo_root)
        return _envelope(runtime, payload)

    @app.get("/api/v1/schwab/performance")
    def schwab_performance(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_schwab_performance(conn, start, end)
        return _envelope(runtime, payload)

    @app.get("/api/v1/performance")
    def performance(
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        strategy_id: str | None = None,
        book_id: str | None = None,
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_strategy_performance(conn, start, end, strategy_id, book_id)
        return _envelope(runtime, payload)

    @app.get("/api/v1/trade/today")
    def trade_today(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict:
        from datetime import date as _date

        runtime: AnalyticsRuntime = app.state.runtime
        trade_date = date or _date.today().isoformat()
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_todays_trades(conn, trade_date, runtime.settings.repo_root)
        return _envelope(runtime, payload)

    @app.get("/api/v1/scan/candidates")
    def scan_candidates(
        date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        symbol: str | None = None,
        direction: str | None = None,
        sector: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        with connect_ro(runtime.settings.db_path) as conn:
            payload = queries.get_scan_candidates(
                conn, date=date, symbol=symbol, direction=direction,
                sector=sector, limit=limit,
            )
        return _envelope(runtime, payload)

    @app.get("/api/v1/scan/chart-data/{symbol}")
    def scan_chart_data(
        symbol: str,
        anchor: str | None = Query(default=None),
        days: int = Query(default=90, ge=10, le=365),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        cache_dir = runtime.settings.repo_root / "cache"
        payload = queries.get_chart_data(cache_dir, symbol, anchor=anchor, days=days)
        return _envelope(runtime, payload)

    # ── Trade Log (CRUD) ─────────────────────────────────
    @app.get("/api/v1/trades/log")
    def list_trades(
        status: str | None = None,
        symbol: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        tl: TradeLogStore = app.state.trade_log
        rows = tl.list_trades(status=status, symbol=symbol, limit=limit)
        return _envelope(runtime, {"trades": rows, "count": len(rows)})

    @app.get("/api/v1/trades/log/summary")
    def trade_log_summary() -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        tl: TradeLogStore = app.state.trade_log
        return _envelope(runtime, tl.get_summary())

    @app.post("/api/v1/trades/log", dependencies=[Depends(require_api_key)])
    def create_trade(body: CreateTradeRequest) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        tl: TradeLogStore = app.state.trade_log
        try:
            row = tl.create(body.model_dump())
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _envelope(runtime, row)

    @app.put("/api/v1/trades/log/{trade_id}", dependencies=[Depends(require_api_key)])
    def close_trade(trade_id: str, body: CloseTradeRequest) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        tl: TradeLogStore = app.state.trade_log
        try:
            row = tl.update_exit(trade_id, body.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _envelope(runtime, row)

    @app.delete("/api/v1/trades/log/{trade_id}", dependencies=[Depends(require_api_key)])
    def delete_trade(trade_id: str) -> dict:
        runtime: AnalyticsRuntime = app.state.runtime
        tl: TradeLogStore = app.state.trade_log
        if not tl.delete(trade_id):
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
        return _envelope(runtime, {"deleted": trade_id})

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
    def root():
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/app")

    dist_dir = cfg.frontend_dist_dir
    if dist_dir.exists():
        index_html = dist_dir / "index.html"

        _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

        @app.get("/app/{path:path}")
        async def spa_fallback(path: str) -> Response:
            static_file = (dist_dir / path).resolve()
            if static_file.is_relative_to(dist_dir.resolve()) and static_file.is_file():
                return FileResponse(static_file, headers=_NO_CACHE)
            return FileResponse(index_html, headers=_NO_CACHE)

        @app.get("/app")
        async def spa_root() -> Response:
            return FileResponse(index_html, headers=_NO_CACHE)

    return app
