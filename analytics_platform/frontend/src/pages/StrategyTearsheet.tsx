/**
 * Strategy Tearsheet — /strategies/:id
 * Full strategy detail page with Atlas design.
 */
import { Link, useParams } from "react-router-dom";
import { ChevronRight } from "lucide-react";

import { api } from "../api";
import { StatusBadge, RegimeBadge, BookBadge } from "../components/Badge";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import { formatPercent, timeAgo } from "../lib/format";
import { getMeta, bookFromId } from "../lib/strategies";
import type {
  AllocationSnapshot,
  JournalRow,
  KeyValue,
  RaecRebalanceEvent,
  ReadinessStrategy,
} from "../types";

/* ── Data extraction ─────────────────────────────── */

function extractRaecSummary(data: KeyValue | null, strategyId: string): any {
  if (!data) return null;
  const byStrategy: any[] = (data as any)?.by_strategy ?? [];
  return byStrategy.find((s: any) => (s.strategy_id as string).toUpperCase() === strategyId.toUpperCase()) ?? null;
}
function extractRaecEvents(data: KeyValue | null, strategyId: string): RaecRebalanceEvent[] {
  if (!data) return [];
  return ((data as any)?.events ?? []).filter(
    (e: RaecRebalanceEvent) => e.strategy_id.toUpperCase() === strategyId.toUpperCase()
  );
}
function extractReadiness(data: KeyValue | null, strategyId: string): ReadinessStrategy | null {
  if (!data) return null;
  return ((data as any)?.strategies ?? []).find(
    (s: ReadinessStrategy) => s.strategy_id.toUpperCase() === strategyId.toUpperCase()
  ) ?? null;
}
function extractJournal(data: KeyValue | null): JournalRow[] {
  if (!data) return [];
  return ((data as any)?.rows ?? []) as JournalRow[];
}
function extractAllocations(data: KeyValue | null, strategyId: string): AllocationSnapshot[] {
  if (!data) return [];
  return ((data as any)?.allocations ?? []).filter(
    (a: AllocationSnapshot) => a.strategy_id.toUpperCase() === strategyId.toUpperCase()
  );
}

/* ── Component ──────────────────────────────────── */

export function StrategyTearsheet() {
  const { id } = useParams<{ id: string }>();
  const strategyId = id ?? "";
  const meta = getMeta(strategyId);
  const book = bookFromId(strategyId);
  const isRaec = meta.type === "raec" || meta.type === "coord";
  const isCoord = meta.type === "coord";

  const raec = usePolling(() => api.raecDashboard({ strategy_id: strategyId }), 45_000);
  const journal = usePolling(() => api.journal({ strategy_id: strategyId, limit: 20 }), 45_000);
  const readiness = usePolling(() => api.raecReadiness(), 60_000);
  const slippage = usePolling(() => api.slippage({ strategy_id: strategyId }), 60_000);

  const isLoading = raec.loading && journal.loading;

  const raecData = raec.data?.data ?? null;
  const raecSummary = extractRaecSummary(raecData, strategyId);
  const raecEvents = extractRaecEvents(raecData, strategyId);
  const journalRows = extractJournal(journal.data?.data ?? null);
  const readinessData = extractReadiness(readiness.data?.data ?? null, strategyId);
  const slippageData = (slippage.data?.data as any)?.summary ?? null;

  const regime: string | null = raecSummary?.latest_regime ?? null;
  const health = !readinessData?.state_file_exists
    ? "error"
    : readinessData.warnings.length > 0
      ? "warn"
      : regime?.toUpperCase().includes("RISK_OFF")
        ? "error"
        : regime?.toUpperCase().includes("TRANSITION")
          ? "warn"
          : "ok";

  const HEALTH_VARIANT = { ok: "active", warn: "warning", error: "error" } as const;
  const lastEval = raecSummary?.last_eval_date ?? readinessData?.last_eval_date ?? null;

  // Merge allocations
  const allocMap = new Map<string, { symbol: string; targetPct: number; currentPct: number }>();
  for (const a of extractAllocations(raecData, strategyId)) {
    const existing = allocMap.get(a.symbol) ?? { symbol: a.symbol, targetPct: 0, currentPct: 0 };
    if (a.alloc_type === "target") existing.targetPct = a.weight_pct;
    else existing.currentPct = a.weight_pct;
    allocMap.set(a.symbol, existing);
  }
  const allocations = [...allocMap.values()].sort((a, b) => b.targetPct - a.targetPct);

  // Coordinator sub-strategies
  const coordSubs = isCoord
    ? ["RAEC_401K_V3", "RAEC_401K_V4", "RAEC_401K_V5"].map((sid) => {
        const sub = extractRaecSummary(raecData, sid);
        const m = getMeta(sid);
        return { id: sid, shortName: m.shortName, subtitle: m.subtitle, regime: sub?.latest_regime, rebalances: sub?.rebalance_count ?? 0 };
      })
    : [];

  // Perf KPIs
  const rebalances = raecSummary?.rebalance_count ?? raecEvents.filter((e) => e.should_rebalance).length;
  const regimeChanges = raecEvents.reduce((c, e, i) => (i > 0 && e.regime !== raecEvents[i - 1].regime ? c + 1 : c), 0);

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-xs text-vantage-muted">
        <Link to="/strategies" className="hover:text-vantage-text transition-colors">Strategies</Link>
        <ChevronRight size={12} />
        <span className="text-vantage-text font-medium">{meta.shortName} \u2014 {meta.subtitle}</span>
      </nav>

      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-1 h-8 rounded-full" style={{ backgroundColor: meta.color }} />
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-semibold">{strategyId}</h2>
            <BookBadge book={book} />
          </div>
          <p className="text-[11px] text-vantage-muted">{meta.shortName} \u2014 {meta.subtitle}</p>
        </div>
      </div>

      {/* Status Bar */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <StatusBadge variant={HEALTH_VARIANT[health]}>
            {health === "ok" ? "ACTIVE" : health === "warn" ? "CAUTION" : "ALERT"}
          </StatusBadge>
          <RegimeBadge regime={regime} />
          <span className="text-xs text-vantage-muted">
            Last Eval: <span className="font-mono">{timeAgo(lastEval)}</span>
          </span>
          {raecSummary?.portfolio_vol_target != null && (
            <span className="text-xs text-vantage-muted">
              Vol Target: <span className="font-mono">{formatPercent(raecSummary.portfolio_vol_target, 1)}</span>
            </span>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          <SkeletonCard />
          <SkeletonTable />
        </div>
      ) : (
        <>
          {/* Coordinator Sub-Strategies */}
          {isCoord && coordSubs.length > 0 && (
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Sub-Strategies (40/30/30 Split)</h3>
              <div className="grid grid-cols-3 gap-3">
                {coordSubs.map((sub) => (
                  <Link
                    key={sub.id}
                    to={`/strategies/${encodeURIComponent(sub.id)}`}
                    className="bg-vantage-bg border border-vantage-border rounded-lg p-3 hover:border-vantage-blue/50 transition-colors"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm font-bold">{sub.shortName}</span>
                      <span className="text-[10px] text-vantage-muted">{sub.subtitle}</span>
                    </div>
                    <RegimeBadge regime={sub.regime} />
                    <p className="text-[10px] text-vantage-muted mt-2">{sub.rebalances} rebalance{sub.rebalances !== 1 ? "s" : ""}</p>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Performance + Signals */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Performance KPIs */}
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Performance</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Rebalances</p>
                  <p className="font-mono text-lg font-bold">{rebalances}</p>
                </div>
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Regime Changes</p>
                  <p className="font-mono text-lg font-bold">{regimeChanges}</p>
                </div>
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Events</p>
                  <p className="font-mono text-lg font-bold">{raecEvents.length}</p>
                </div>
                {slippageData && (
                  <div>
                    <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Avg Slippage</p>
                    <p className="font-mono text-lg font-bold">{(slippageData.mean_bps ?? 0).toFixed(1)} bps</p>
                  </div>
                )}
              </div>
            </div>

            {/* Allocation */}
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Allocation</h3>
              {allocations.length > 0 ? (
                <div className="space-y-2">
                  {allocations.map((a) => (
                    <div key={a.symbol} className="flex items-center gap-3">
                      <span className="font-mono text-xs font-semibold w-12">{a.symbol}</span>
                      <div className="flex-1">
                        <div className="h-1.5 bg-vantage-border rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full bg-vantage-blue transition-all duration-500"
                            style={{ width: `${Math.min(a.targetPct, 100)}%`, opacity: 0.8 }}
                          />
                        </div>
                      </div>
                      <span className="font-mono text-xs text-vantage-muted w-12 text-right">{a.targetPct.toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-vantage-muted">Allocation data populated after rebalance events</p>
              )}
            </div>
          </div>

          {/* Blotter */}
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Blotter <span className="text-vantage-muted font-normal">(recent)</span></h3>
              <Link
                to={`/blotter?strategy_id=${encodeURIComponent(strategyId)}`}
                className="text-[11px] text-vantage-blue hover:text-vantage-blue/80 transition-colors"
              >
                View all &rarr;
              </Link>
            </div>
            {journalRows.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-vantage-border">
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Date</th>
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Side</th>
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Symbol</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Delta %</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Target %</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Current %</th>
                      <th className="py-2 px-2 text-center text-vantage-muted font-medium">Posted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {journalRows.map((row, i) => (
                      <tr
                        key={`${row.ny_date}-${row.symbol}-${i}`}
                        className={`border-b border-vantage-border/50 ${
                          row.side === "BUY" ? "bg-vantage-green/[0.03] hover:bg-vantage-green/[0.05]" : "bg-vantage-red/[0.03] hover:bg-vantage-red/[0.05]"
                        }`}
                      >
                        <td className="py-2 px-2 font-mono">{row.ny_date}</td>
                        <td className={`py-2 px-2 font-mono font-semibold ${row.side === "BUY" ? "text-vantage-green" : "text-vantage-red"}`}>
                          {row.side}
                        </td>
                        <td className="py-2 px-2 font-mono font-semibold">{row.symbol}</td>
                        <td className="py-2 px-2 font-mono text-right">
                          {row.delta_pct != null ? `${row.delta_pct > 0 ? "+" : ""}${row.delta_pct.toFixed(1)}%` : "\u2014"}
                        </td>
                        <td className="py-2 px-2 font-mono text-right">
                          {row.target_pct != null ? `${row.target_pct.toFixed(1)}%` : "\u2014"}
                        </td>
                        <td className="py-2 px-2 font-mono text-right">
                          {row.current_pct != null ? `${row.current_pct.toFixed(1)}%` : "\u2014"}
                        </td>
                        <td className="py-2 px-2 text-center">
                          {row.posted ? (
                            <span className="text-vantage-green">\u2713</span>
                          ) : (
                            <span className="text-vantage-muted">\u2014</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-vantage-muted py-4 text-center">No recent journal entries</p>
            )}
          </div>

          {/* Readiness Check */}
          {isRaec && readinessData && (
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Readiness Check</h3>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">State File</p>
                  <StatusBadge variant={readinessData.state_file_exists ? "active" : "error"}>
                    {readinessData.state_file_exists ? "OK" : "MISSING"}
                  </StatusBadge>
                </div>
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Allocations</p>
                  <p className="font-mono text-xs font-semibold">{readinessData.allocation_count} ({readinessData.total_weight_pct.toFixed(0)}%)</p>
                </div>
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Ledger Today</p>
                  <p className="font-mono text-xs font-semibold">{readinessData.today_ledger_count} files</p>
                </div>
                <div>
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Warnings</p>
                  <p className="font-mono text-xs font-semibold">{readinessData.warnings.length}</p>
                </div>
              </div>
              {readinessData.warnings.length > 0 && (
                <div className="mt-3 space-y-1">
                  {readinessData.warnings.map((w, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs text-vantage-amber">
                      <span>\u25B2</span> {w}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
