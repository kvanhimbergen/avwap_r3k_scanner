/**
 * Command Center — the home dashboard.
 * Atlas design: stat cards row, book panels, strategy grid, alerts + activity feed.
 */
import { Link } from "react-router-dom";
import { Activity, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";

import { api } from "../api";
import { StatCard } from "../components/StatCard";
import { StatusBadge, RegimeBadge, BookBadge } from "../components/Badge";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, pnlColor, fmtUsdCompact, timeAgo } from "../lib/format";
import { getMeta, bookFromId, regimeColor } from "../lib/strategies";
import type {
  FreshnessRow,
  JournalRow,
  KeyValue,
  PortfolioPosition,
  RaecRebalanceEvent,
  ReadinessStrategy,
  StrategyMatrixRow,
} from "../types";

/* ── Data extraction helpers ───────────────────────── */

function extractStrategies(data: KeyValue | null): StrategyMatrixRow[] {
  if (!data) return [];
  return ((data as any).strategies ?? (data as any).rows ?? []) as StrategyMatrixRow[];
}

function extractRaecSummary(data: KeyValue | null): any[] {
  if (!data) return [];
  return (data as any)?.by_strategy ?? [];
}

function extractRaecEvents(data: KeyValue | null): RaecRebalanceEvent[] {
  if (!data) return [];
  return ((data as any)?.events ?? []) as RaecRebalanceEvent[];
}

function extractReadiness(data: KeyValue | null): ReadinessStrategy[] {
  if (!data) return [];
  return ((data as any)?.strategies ?? []) as ReadinessStrategy[];
}

function extractJournal(data: KeyValue | null): JournalRow[] {
  if (!data) return [];
  return ((data as any)?.rows ?? []) as JournalRow[];
}

/* ── Health computation ─────────────────────────── */

function computeHealth(
  regime: string | null,
  readiness: ReadinessStrategy | undefined,
  freshnessRows: FreshnessRow[],
): "ok" | "warn" | "error" {
  if (regime?.toUpperCase().includes("RISK_OFF")) return "error";
  if (readiness) {
    if (!readiness.state_file_exists) return "error";
    if (readiness.warnings.length > 0) return "warn";
  }
  const now = Date.now();
  for (const row of freshnessRows) {
    if (!row.latest_mtime_utc) continue;
    const ageH = (now - new Date(row.latest_mtime_utc).getTime()) / 3_600_000;
    if (row.parse_status === "error") return "error";
    if (ageH > 4) return "warn";
  }
  if (regime?.toUpperCase().includes("TRANSITION")) return "warn";
  return "ok";
}

const HEALTH_VARIANT = { ok: "active", warn: "warning", error: "error" } as const;

/* ── Component ──────────────────────────────────── */

export function CommandCenter() {
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);
  const matrix = usePolling(() => api.strategyMatrix(), 45_000);
  const raec = usePolling(() => api.raecDashboard(), 45_000);
  const readiness = usePolling(() => api.raecReadiness(), 60_000);
  const journal = usePolling(() => api.journal({ limit: 50 }), 45_000);
  const freshness = usePolling(() => api.freshness(), 60_000);
  const schwab = usePolling(() => api.schwabOverview(), 60_000);

  const isLoading = matrix.loading || raec.loading;
  const error = matrix.error || raec.error;

  const strategies = extractStrategies(matrix.data?.data ?? null);
  const raecSummary = extractRaecSummary(raec.data?.data ?? null);
  const raecEvents = extractRaecEvents(raec.data?.data ?? null);
  const readinessStrategies = extractReadiness(readiness.data?.data ?? null);
  const freshnessRows = (freshness.data?.data?.rows ?? []) as FreshnessRow[];
  const journalRows = extractJournal(journal.data?.data ?? null);

  // Portfolio metrics
  const latest = (portfolio.data?.data as any)?.latest ?? {};
  const capitalTotal = latest.capital_total as number | undefined;
  const dayPnl = (latest.realized_pnl ?? latest.unrealized_pnl) as number | undefined;

  // Schwab metrics
  const schwabAccount = (schwab.data?.data as any)?.latest_account ?? null;
  const schwabCapital = schwabAccount?.total_value as number | undefined;

  // Strategy count
  const activeCount = strategies.length;

  // Build alerts
  const alerts: { severity: "error" | "warn"; text: string; strategyId?: string }[] = [];
  for (const r of readinessStrategies) {
    if (!r.state_file_exists) alerts.push({ severity: "error", text: "State file missing", strategyId: r.strategy_id });
    for (const w of r.warnings) alerts.push({ severity: "warn", text: w, strategyId: r.strategy_id });
  }
  const now = Date.now();
  for (const row of freshnessRows) {
    if (row.parse_status === "error") alerts.push({ severity: "error", text: `Parse error: ${row.source_name}` });
    if (row.latest_mtime_utc) {
      const ageH = (now - new Date(row.latest_mtime_utc).getTime()) / 3_600_000;
      if (ageH > 4) alerts.push({ severity: "warn", text: `${row.source_name} data ${Math.round(ageH)}h stale` });
    }
  }

  // Build activity feed
  const feedEvents: { time: string; type: string; strategyId: string; text: string }[] = [];
  for (const ev of raecEvents) {
    if (ev.should_rebalance) {
      feedEvents.push({
        time: ev.ny_date,
        type: "rebalance",
        strategyId: getMeta(ev.strategy_id).shortName,
        text: `rebalanced (${ev.intent_count} intent${ev.intent_count !== 1 ? "s" : ""})`,
      });
    }
  }
  for (const row of journalRows.slice(0, 30)) {
    const t = row.ts_utc
      ? new Date(row.ts_utc).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" })
      : row.ny_date;
    feedEvents.push({
      time: t,
      type: row.posted ? "fill" : "info",
      strategyId: getMeta(row.strategy_id).shortName,
      text: `${row.side} ${row.symbol} ${row.delta_pct != null ? `${row.delta_pct > 0 ? "+" : ""}${row.delta_pct.toFixed(1)}%` : ""}`,
    });
  }
  feedEvents.sort((a, b) => b.time.localeCompare(a.time));

  // Build strategy cards
  const readinessMap = new Map<string, ReadinessStrategy>();
  for (const r of readinessStrategies) readinessMap.set(r.strategy_id.toUpperCase(), r);
  const raecMap = new Map<string, any>();
  for (const s of raecSummary) raecMap.set((s.strategy_id as string).toUpperCase(), s);

  if (isLoading) {
    return (
      <div className="space-y-4 h-full">
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (error) return <ErrorState message={error} />;

  return (
    <div className="space-y-4 h-full">
      {/* Row 1: Stat Cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Equity (Alpaca)" value={capitalTotal != null ? formatCurrency(capitalTotal, 0) : "\u2014"} />
        <StatCard label="Day P&L" value={dayPnl != null ? formatCurrency(dayPnl, 0) : "\u2014"} numericValue={dayPnl} />
        <StatCard label="Schwab 401K" value={schwabCapital != null ? formatCurrency(schwabCapital, 0) : "\u2014"} />
        <StatCard label="Active Strategies" value={String(activeCount)} />
      </div>

      {/* Row 2: Strategy Grid */}
      <div>
        <h3 className="text-sm font-semibold mb-3">Strategy Status</h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {strategies.map((s) => {
            const upper = s.strategy_id.toUpperCase();
            const meta = getMeta(s.strategy_id);
            const raecRow = raecMap.get(upper);
            const rd = readinessMap.get(upper);
            const regime = raecRow?.latest_regime ?? s.latest_regime ?? null;
            const health = computeHealth(regime, rd, freshnessRows);
            const isRaec = upper.includes("RAEC");
            const metricVal = isRaec ? (raecRow?.rebalance_count ?? 0) : s.trade_count;
            const metricLbl = isRaec ? "reb" : "trades";

            return (
              <Link
                key={s.strategy_id}
                to={`/strategies/${encodeURIComponent(s.strategy_id)}`}
                className="bg-vantage-card border border-vantage-border rounded-lg p-4 border-l-2 hover:border-vantage-blue/50 transition-colors"
                style={{ borderLeftColor: meta.color }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{meta.shortName}</span>
                    <span className="text-[10px] text-vantage-muted">{meta.subtitle}</span>
                  </div>
                  <StatusBadge variant={HEALTH_VARIANT[health]}>
                    {health === "ok" ? "ACTIVE" : health === "warn" ? "WARN" : "ALERT"}
                  </StatusBadge>
                </div>
                <div className="flex items-center gap-3">
                  <RegimeBadge regime={regime} />
                  <span className="font-mono text-xs text-vantage-muted">
                    {metricVal} {metricLbl}
                  </span>
                </div>
              </Link>
            );
          })}
          {strategies.length === 0 && (
            <div className="col-span-full">
              <EmptyState message="No strategies found" />
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Alerts + Activity Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" style={{ minHeight: 280 }}>
        {/* Alerts */}
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 h-full flex flex-col">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle size={16} className="text-vantage-amber" />
            Alerts
            {alerts.length > 0 && (
              <span className="text-[9px] px-1 py-0.5 rounded-full font-mono bg-vantage-border text-vantage-muted">
                {alerts.length}
              </span>
            )}
          </h3>
          <div className="flex-1 overflow-y-auto min-h-0 space-y-2">
            {alerts.length === 0 ? (
              <p className="text-xs text-vantage-muted">No active alerts</p>
            ) : (
              alerts.slice(0, 20).map((a, i) => (
                <div key={i} className={`flex items-start gap-2 text-xs px-2 py-1.5 rounded ${
                  a.severity === "error" ? "bg-vantage-red/[0.03]" : "bg-vantage-amber/[0.03]"
                }`}>
                  <span className={`mt-0.5 ${a.severity === "error" ? "text-vantage-red" : "text-vantage-amber"}`}>
                    {a.severity === "error" ? "\u25CF" : "\u25B2"}
                  </span>
                  <span className="text-vantage-text">
                    {a.strategyId && <span className="font-mono font-semibold mr-1">{getMeta(a.strategyId).shortName}</span>}
                    {a.text}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Activity Feed */}
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 h-full flex flex-col">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Activity size={16} className="text-vantage-blue" />
            Activity Feed
          </h3>
          <div className="flex-1 overflow-y-auto min-h-0 space-y-1.5">
            {feedEvents.length === 0 ? (
              <p className="text-xs text-vantage-muted">No recent activity</p>
            ) : (
              feedEvents.slice(0, 30).map((ev, i) => (
                <div key={i} className="flex items-center gap-2 text-xs py-1">
                  <span className="font-mono text-vantage-muted w-12 shrink-0">{ev.time}</span>
                  <span className={`font-mono font-semibold w-10 shrink-0 ${
                    ev.type === "rebalance" ? "text-vantage-blue" : ev.type === "fill" ? "text-vantage-green" : "text-vantage-muted"
                  }`}>{ev.strategyId}</span>
                  <span className="text-vantage-text truncate">{ev.text}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
