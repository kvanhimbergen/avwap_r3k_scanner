/**
 * Strategy Tearsheet — full strategy detail page at /strategies/:id.
 * Everything about one strategy on one page. The PM's "fact sheet."
 *
 * Sections (top to bottom):
 *  1. Status Bar — active/regime/last eval/vol
 *  2. Allocation — target vs current (AllocationBar)
 *  3. Key Signals — SMA, vol, momentum (SignalsPanel)
 *  4. Performance — KPIs (PerformancePanel)
 *  5. Blotter — recent journal rows for this strategy
 *  6. Readiness Check — state/eval/ledger health (RAEC only)
 *  7. Execution Quality — slippage stats (S1/S2 only)
 */
import { useParams } from "react-router-dom";

import { api } from "../api";
import { AllocationBar, type AllocationRow } from "../components/AllocationBar";
import { BookBadge, bookFromId } from "../components/BookBadge";
import { BreadcrumbNav } from "../components/BreadcrumbNav";
import { ControlActions } from "../components/ControlActions";
import { LastRefreshed } from "../components/LastRefreshed";
import { PerformancePanel, type PerformanceData } from "../components/PerformancePanel";
import { ReadinessCheck } from "../components/ReadinessCheck";
import { RegimeBadge } from "../components/RegimeBadge";
import { SignalsPanel, type SignalRow } from "../components/SignalsPanel";
import { SkeletonLoader } from "../components/SkeletonLoader";
import { StatusDot } from "../components/StatusDot";
import { SummaryStrip } from "../components/SummaryStrip";
import { usePolling } from "../hooks/usePolling";
import type {
  AllocationSnapshot,
  JournalRow,
  KeyValue,
  RaecRebalanceEvent,
  ReadinessStrategy,
} from "../types";

/* ── Strategy metadata ──────────────────────────────────── */

interface StrategyMeta {
  shortName: string;
  subtitle: string;
  type: "s1" | "s2" | "raec" | "coord";
}

const META: Record<string, StrategyMeta> = {
  S1_AVWAP_CORE: { shortName: "S1", subtitle: "AVWAP Core", type: "s1" },
  S2_LETF_ORB_AGGRO: { shortName: "S2", subtitle: "LETF ORB Aggro", type: "s2" },
  RAEC_401K_V1: { shortName: "V1", subtitle: "Core", type: "raec" },
  RAEC_401K_V2: { shortName: "V2", subtitle: "Enhanced", type: "raec" },
  RAEC_401K_V3: { shortName: "V3", subtitle: "Aggressive", type: "raec" },
  RAEC_401K_V4: { shortName: "V4", subtitle: "Macro", type: "raec" },
  RAEC_401K_V5: { shortName: "V5", subtitle: "AI/Tech", type: "raec" },
  RAEC_401K_COORD: { shortName: "COORD", subtitle: "40/30/30 Coordinator", type: "coord" },
};

function getMeta(id: string): StrategyMeta {
  const upper = id.toUpperCase();
  if (META[upper]) return META[upper];
  for (const [key, val] of Object.entries(META)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  const isS = upper.startsWith("S1") || upper.startsWith("S2");
  return { shortName: id.split("_").pop() ?? id, subtitle: id, type: isS ? "s1" : "raec" };
}

/* ── Helpers ─────────────────────────────────────────────── */

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return `${v.toFixed(1)}%`;
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "\u2014";
  const ms = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "< 1h ago";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function extractRaecEvents(data: KeyValue | null, strategyId: string): RaecRebalanceEvent[] {
  if (!data) return [];
  const events = ((data as any)?.events ?? []) as RaecRebalanceEvent[];
  return events.filter((e) => e.strategy_id.toUpperCase() === strategyId.toUpperCase());
}

function extractRaecSummary(data: KeyValue | null, strategyId: string): any {
  if (!data) return null;
  const byStrategy: any[] = (data as any)?.by_strategy ?? [];
  return byStrategy.find((s: any) => (s.strategy_id as string).toUpperCase() === strategyId.toUpperCase()) ?? null;
}

function extractReadiness(data: KeyValue | null, strategyId: string): ReadinessStrategy | null {
  if (!data) return null;
  const strategies = ((data as any)?.strategies ?? []) as ReadinessStrategy[];
  return strategies.find((s) => s.strategy_id.toUpperCase() === strategyId.toUpperCase()) ?? null;
}

function extractJournal(data: KeyValue | null): JournalRow[] {
  if (!data) return [];
  return ((data as any)?.rows ?? []) as JournalRow[];
}

function extractAllocations(data: KeyValue | null, strategyId: string): AllocationSnapshot[] {
  if (!data) return [];
  const events = ((data as any)?.events ?? []) as RaecRebalanceEvent[];
  // Find latest event for this strategy that has allocations
  const stEvents = events.filter(
    (e) => e.strategy_id.toUpperCase() === strategyId.toUpperCase() && e.should_rebalance
  );
  // Allocations may be in a different field — fall back to extracting from journal
  return ((data as any)?.allocations ?? []).filter(
    (a: AllocationSnapshot) => a.strategy_id.toUpperCase() === strategyId.toUpperCase()
  );
}

function extractSlippage(data: KeyValue | null): any {
  if (!data) return null;
  return (data as any)?.summary ?? null;
}

function extractTradeAnalytics(data: KeyValue | null, strategyId: string): any {
  if (!data) return null;
  const byStrategy: any[] = (data as any)?.by_strategy ?? [];
  return byStrategy.find((s: any) => (s.strategy_id as string).toUpperCase() === strategyId.toUpperCase()) ?? null;
}

/* ── Component ──────────────────────────────────────────── */

export function StrategyTearsheet() {
  const { id } = useParams<{ id: string }>();
  const strategyId = id ?? "";
  const meta = getMeta(strategyId);
  const book = bookFromId(strategyId);
  const isAlpaca = book === "alpaca";
  const isRaec = meta.type === "raec" || meta.type === "coord";
  const isCoord = meta.type === "coord";

  // API calls
  const raec = usePolling(() => api.raecDashboard({ strategy_id: strategyId }), 45_000);
  const journal = usePolling(() => api.journal({ strategy_id: strategyId, limit: 20 }), 45_000);
  const readiness = usePolling(() => api.raecReadiness(), 60_000);
  const slippage = usePolling(
    () => api.slippage({ strategy_id: strategyId }),
    isAlpaca ? 60_000 : 300_000,
  );
  const trades = usePolling(
    () => api.tradeAnalytics({ strategy_id: strategyId }),
    isAlpaca ? 60_000 : 300_000,
  );

  const isLoading = raec.loading && journal.loading;

  // Extract data
  const raecData = raec.data?.data ?? null;
  const raecSummary = extractRaecSummary(raecData, strategyId);
  const raecEvents = extractRaecEvents(raecData, strategyId);
  const journalRows = extractJournal(journal.data?.data ?? null);
  const readinessData = extractReadiness(readiness.data?.data ?? null, strategyId);
  const slippageData = extractSlippage(slippage.data?.data ?? null);
  const tradeData = extractTradeAnalytics(trades.data?.data ?? null, strategyId);

  // Derive regime
  const regime: string | null = raecSummary?.latest_regime ?? null;

  // Derive health
  const health = !readinessData?.state_file_exists
    ? "error"
    : readinessData && readinessData.warnings.length > 0
      ? "warn"
      : regime?.toUpperCase().includes("RISK_OFF")
        ? "error"
        : regime?.toUpperCase().includes("TRANSITION")
          ? "warn"
          : "ok";

  // Build allocations from raec events/allocations
  const allocations: AllocationRow[] = extractAllocations(raecData, strategyId).map((a) => ({
    symbol: a.symbol,
    targetPct: a.alloc_type === "target" ? a.weight_pct : 0,
    currentPct: a.alloc_type === "current" ? a.weight_pct : 0,
  }));

  // Merge target + current for same symbol
  const allocMap = new Map<string, AllocationRow>();
  for (const a of extractAllocations(raecData, strategyId)) {
    const existing = allocMap.get(a.symbol) ?? { symbol: a.symbol, targetPct: 0, currentPct: 0 };
    if (a.alloc_type === "target") existing.targetPct = a.weight_pct;
    else existing.currentPct = a.weight_pct;
    allocMap.set(a.symbol, existing);
  }
  const mergedAllocations = [...allocMap.values()].sort((a, b) => b.targetPct - a.targetPct);

  // Build signals from raec summary
  const signals: SignalRow[] = [];
  if (raecSummary?.vol_target != null) {
    signals.push({ label: "Vol Target", value: fmtPct(raecSummary.vol_target) });
  }
  if (raecSummary?.realized_vol != null) {
    signals.push({ label: "Vol Realized", value: fmtPct(raecSummary.realized_vol) });
  }

  // Performance data
  const perfData: PerformanceData = {
    rebalances: raecSummary?.rebalances ?? raecEvents.filter((e) => e.should_rebalance).length,
    regimeChanges: raecEvents.reduce((count, e, i) => {
      if (i === 0) return count;
      return e.regime !== raecEvents[i - 1].regime ? count + 1 : count;
    }, 0),
    avgDrift: null,
    events: raecEvents.length,
    trades: tradeData?.trade_count,
    uniqueSymbols: tradeData?.unique_symbols,
  };

  // Last eval time
  const lastEval = raecSummary?.last_eval_date ?? readinessData?.last_eval_date ?? null;

  // Coordinator sub-strategies
  const coordSubStrategies = isCoord
    ? ["RAEC_401K_V3", "RAEC_401K_V4", "RAEC_401K_V5"].map((sid) => {
        const sub = extractRaecSummary(raecData, sid);
        const subMeta = getMeta(sid);
        return {
          strategyId: sid,
          shortName: subMeta.shortName,
          subtitle: subMeta.subtitle,
          regime: sub?.latest_regime ?? null,
          rebalances: sub?.rebalances ?? 0,
        };
      })
    : [];

  return (
    <section>
      <BreadcrumbNav
        crumbs={[
          { label: "Strategies", to: "/strategies" },
          { label: `${meta.shortName} \u2014 ${meta.subtitle}` },
        ]}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <h2 className="page-title" style={{ margin: 0 }}>
          {strategyId}
        </h2>
        <BookBadge strategyId={strategyId} />
        <LastRefreshed at={raec.lastRefreshed ?? journal.lastRefreshed} />
      </div>
      <p className="page-subtitle">
        {meta.shortName} \u2014 {meta.subtitle}
      </p>

      {/* ── Status Bar ────────────────────────────────────── */}
      <div className="tearsheet-status-bar">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <StatusDot status={health as any} large />
            <span className="font-bold" style={{ textTransform: "uppercase", fontSize: "0.82rem" }}>
              {health === "error" ? "Alert" : "Active"}
            </span>
            <RegimeBadge regime={regime} />
            <span className="text-secondary" style={{ fontSize: "0.78rem" }}>
              Last Eval: <span className="font-mono">{timeAgo(lastEval)}</span>
            </span>
            {raecSummary?.vol_target != null && raecSummary?.realized_vol != null && (
              <span className="text-secondary" style={{ fontSize: "0.78rem" }}>
                Vol: <span className="font-mono">{fmtPct(raecSummary.realized_vol)}/{fmtPct(raecSummary.vol_target)}</span>
              </span>
            )}
          </div>
          <ControlActions strategyId={strategyId} />
        </div>
      </div>

      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SkeletonLoader variant="card" />
          <SkeletonLoader variant="chart" />
          <SkeletonLoader variant="card" />
        </div>
      ) : (
        <>
          {/* ── Coordinator Sub-Strategies ──────────────────── */}
          {isCoord && coordSubStrategies.length > 0 && (
            <div className="table-card">
              <h3>Sub-Strategies (40/30/30 Split)</h3>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                {coordSubStrategies.map((sub) => (
                  <div key={sub.strategyId} className="data-card">
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                      <span className="font-bold" style={{ fontSize: "0.82rem" }}>{sub.shortName}</span>
                      <span className="text-tertiary" style={{ fontSize: "0.72rem" }}>{sub.subtitle}</span>
                    </div>
                    <RegimeBadge regime={sub.regime} />
                    <div className="text-secondary" style={{ fontSize: "0.72rem", marginTop: 4 }}>
                      {sub.rebalances} rebalance{sub.rebalances !== 1 ? "s" : ""}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Allocation + Signals (side by side) ────────── */}
          <div className="two-col" style={{ marginTop: 16 }}>
            <div className="table-card" style={{ marginTop: 0 }}>
              <h3>Allocation</h3>
              {mergedAllocations.length > 0 ? (
                <>
                  <AllocationBar rows={mergedAllocations} />
                  {(() => {
                    const drift = mergedAllocations.reduce(
                      (sum, r) => sum + Math.abs(r.targetPct - r.currentPct),
                      0,
                    );
                    return drift > 0 ? (
                      <div className="text-secondary" style={{ fontSize: "0.72rem", marginTop: 8 }}>
                        Total drift: <span className="font-mono">{drift.toFixed(1)}%</span> off target
                      </div>
                    ) : null;
                  })()}
                </>
              ) : (
                <div className="text-tertiary" style={{ fontSize: "0.78rem" }}>
                  {isAlpaca
                    ? "Position data from portfolio endpoint"
                    : "Allocation data populated after rebalance events"}
                </div>
              )}
            </div>

            <div className="table-card" style={{ marginTop: 0 }}>
              <h3>Key Signals</h3>
              <SignalsPanel
                signals={signals}
                volTarget={raecSummary?.vol_target}
                volRealized={raecSummary?.realized_vol}
              />
            </div>
          </div>

          {/* ── Performance ──────────────────────────────────── */}
          <div className="table-card">
            <h3>Performance</h3>
            <PerformancePanel data={perfData} />
          </div>

          {/* ── Blotter (recent) ─────────────────────────────── */}
          <div className="table-card">
            <h3>
              Blotter{" "}
              <span className="text-tertiary" style={{ fontSize: "0.72rem", fontWeight: 400 }}>
                (recent)
              </span>
            </h3>
            {journalRows.length > 0 ? (
              <>
                <SummaryStrip
                  items={[
                    { label: "Total", value: journalRows.length },
                    { label: "Buys", value: journalRows.filter((r) => r.side === "BUY").length },
                    { label: "Sells", value: journalRows.filter((r) => r.side === "SELL").length },
                  ]}
                />
                <div style={{ overflowX: "auto" }}>
                  <table className="journal-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Side</th>
                        <th>Symbol</th>
                        <th>Delta %</th>
                        <th>Target %</th>
                        <th>Current %</th>
                        <th>Posted</th>
                      </tr>
                    </thead>
                    <tbody>
                      {journalRows.map((row, i) => (
                        <tr key={`${row.ny_date}-${row.symbol}-${i}`}>
                          <td className="font-mono">{row.ny_date}</td>
                          <td className={row.side === "BUY" ? "side-buy" : "side-sell"}>{row.side}</td>
                          <td className="font-mono font-bold">{row.symbol}</td>
                          <td className="font-mono">
                            {row.delta_pct > 0 ? "+" : ""}{row.delta_pct.toFixed(1)}%
                          </td>
                          <td className="font-mono">{row.target_pct.toFixed(1)}%</td>
                          <td className="font-mono">{row.current_pct.toFixed(1)}%</td>
                          <td>{row.posted ? "\u2713" : "\u2014"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ marginTop: 8, fontSize: "0.72rem" }}>
                  <a href={`/blotter?strategy_id=${encodeURIComponent(strategyId)}`} style={{ color: "var(--accent)" }}>
                    View full blotter for {meta.shortName} \u2192
                  </a>
                </div>
              </>
            ) : (
              <div className="empty-state">No recent journal entries</div>
            )}
          </div>

          {/* ── Readiness Check (RAEC only) ──────────────────── */}
          {isRaec && (
            <div className="table-card">
              <h3>Readiness Check</h3>
              <ReadinessCheck data={readinessData} />
            </div>
          )}

          {/* ── Execution Quality (S1/S2 Alpaca only) ────────── */}
          {isAlpaca && slippageData && (
            <div className="table-card">
              <h3>Execution Quality</h3>
              <SummaryStrip
                items={[
                  { label: "Mean Slippage", value: `${(slippageData.mean_bps ?? 0).toFixed(1)} bps` },
                  { label: "Median", value: `${(slippageData.median_bps ?? 0).toFixed(1)} bps` },
                  { label: "P95", value: `${(slippageData.p95_bps ?? 0).toFixed(1)} bps` },
                  { label: "Executions", value: slippageData.total ?? 0 },
                ]}
              />
            </div>
          )}
        </>
      )}
    </section>
  );
}
