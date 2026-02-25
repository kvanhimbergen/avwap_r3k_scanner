/**
 * Strategy Roster — /strategies
 * Atlas design: book-grouped strategy cards with colored left borders,
 * allocation donut placeholder, filter controls.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { Layers, ChevronRight } from "lucide-react";

import { api } from "../api";
import { StatusBadge, RegimeBadge, BookBadge } from "../components/Badge";
import { SkeletonCard } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency } from "../lib/format";
import { getMeta, bookFromId, regimeColor } from "../lib/strategies";
import type {
  FreshnessRow,
  KeyValue,
  RaecRebalanceEvent,
  ReadinessStrategy,
  StrategyMatrixRow,
  SymbolOverlap,
} from "../types";

/* ── Data extraction ─────────────────────────────── */

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
function extractOverlaps(data: KeyValue | null): SymbolOverlap[] {
  if (!data) return [];
  return ((data as any).symbol_overlap ?? []) as SymbolOverlap[];
}

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

type BookFilter = "all" | "alpaca" | "schwab";

/* ── Component ──────────────────────────────────── */

export function StrategyRoster() {
  const [bookFilter, setBookFilter] = useState<BookFilter>("all");

  const matrix = usePolling(() => api.strategyMatrix(), 45_000);
  const raec = usePolling(() => api.raecDashboard(), 45_000);
  const readiness = usePolling(() => api.raecReadiness(), 60_000);
  const freshness = usePolling(() => api.freshness(), 60_000);
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);

  const isLoading = matrix.loading || raec.loading;
  const error = matrix.error || raec.error;

  const strategies = extractStrategies(matrix.data?.data ?? null);
  const raecSummary = extractRaecSummary(raec.data?.data ?? null);
  const raecEvents = extractRaecEvents(raec.data?.data ?? null);
  const readinessStrategies = extractReadiness(readiness.data?.data ?? null);
  const freshnessRows = (freshness.data?.data?.rows ?? []) as FreshnessRow[];
  const overlaps = extractOverlaps(matrix.data?.data ?? null);

  // Index helpers
  const readinessMap = new Map<string, ReadinessStrategy>();
  for (const r of readinessStrategies) readinessMap.set(r.strategy_id.toUpperCase(), r);
  const raecMap = new Map<string, any>();
  for (const s of raecSummary) raecMap.set((s.strategy_id as string).toUpperCase(), s);
  const capitalTotal = (portfolio.data?.data as any)?.latest?.capital_total as number | undefined;

  // Build cards for a given book
  function renderBookSection(bookKey: "alpaca" | "schwab", title: string) {
    const bookStrategies = strategies.filter((s) => bookFromId(s.strategy_id, s.book_id) === bookKey);
    if (bookStrategies.length === 0) return null;

    const bookRebalances = raecSummary
      .filter((s: any) => bookFromId(s.strategy_id ?? "", s.book_id) === bookKey)
      .reduce((sum: number, s: any) => sum + (s.rebalance_count ?? 0), 0);

    return (
      <div className="space-y-3">
        {/* Book header */}
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold">{title}</h3>
          <BookBadge book={bookKey} />
          <span className="text-xs text-vantage-muted">
            {bookStrategies.length} strategies
            {bookRebalances > 0 ? ` \u00B7 ${bookRebalances} rebalances` : ""}
            {bookKey === "alpaca" && capitalTotal != null ? ` \u00B7 ${formatCurrency(capitalTotal, 0)}` : ""}
          </span>
        </div>

        {/* Strategy cards */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {bookStrategies.map((s) => {
            const upper = s.strategy_id.toUpperCase();
            const meta = getMeta(s.strategy_id);
            const raecRow = raecMap.get(upper);
            const rd = readinessMap.get(upper);
            const regime = raecRow?.latest_regime ?? s.latest_regime ?? null;
            const health = computeHealth(regime, rd, freshnessRows);
            const isRaec = upper.includes("RAEC");
            const rebalances = raecRow?.rebalance_count ?? 0;

            return (
              <Link
                key={s.strategy_id}
                to={`/strategies/${encodeURIComponent(s.strategy_id)}`}
                className="bg-vantage-card border border-vantage-border rounded-lg p-4 border-l-2 hover:border-vantage-blue/50 transition-colors group"
                style={{ borderLeftColor: meta.color }}
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{meta.shortName}</span>
                    <span className="text-[11px] text-vantage-muted">{meta.subtitle}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge variant={HEALTH_VARIANT[health]}>
                      {health === "ok" ? "ACTIVE" : health === "warn" ? "WARN" : "ALERT"}
                    </StatusBadge>
                    <ChevronRight size={14} className="text-vantage-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                </div>

                <div className="flex items-center gap-3 mb-3">
                  <RegimeBadge regime={regime} />
                </div>

                {/* Metrics grid */}
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Trades</p>
                    <p className="font-mono text-xs font-semibold">{s.trade_count}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Symbols</p>
                    <p className="font-mono text-xs font-semibold">{s.unique_symbols}</p>
                  </div>
                  {isRaec && (
                    <div>
                      <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Rebalances</p>
                      <p className="font-mono text-xs font-semibold">{rebalances}</p>
                    </div>
                  )}
                </div>

                {/* Allocation bar */}
                {rd && rd.has_allocations && rd.total_weight_pct > 0 && (
                  <div className="mt-3">
                    <div className="h-1.5 bg-vantage-border rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${Math.min(rd.total_weight_pct, 100)}%`, backgroundColor: meta.color, opacity: 0.8 }}
                      />
                    </div>
                    <p className="text-[10px] text-vantage-muted mt-1">{rd.total_weight_pct.toFixed(0)}% allocated</p>
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Layers size={24} className="text-vantage-blue" />
          <div>
            <h2 className="text-xl font-semibold">Strategies</h2>
            <p className="text-[11px] text-vantage-muted">
              {strategies.length} active strategies across {new Set(strategies.map((s) => bookFromId(s.strategy_id, s.book_id))).size} books
            </p>
          </div>
        </div>

        {/* Filter pills */}
        <div className="flex items-center gap-2">
          {(["all", "alpaca", "schwab"] as BookFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setBookFilter(f)}
              className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                bookFilter === f
                  ? "bg-vantage-border text-vantage-text"
                  : "text-vantage-muted hover:text-vantage-text"
              }`}
            >
              {f === "all" ? "All" : f === "alpaca" ? "Alpaca" : "Schwab"}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 gap-4">
          {[...Array(6)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : error ? (
        <ErrorState message={error} />
      ) : (
        <div className="space-y-8">
          {(bookFilter === "all" || bookFilter === "alpaca") &&
            renderBookSection("alpaca", "Alpaca Paper")}
          {(bookFilter === "all" || bookFilter === "schwab") &&
            renderBookSection("schwab", "Schwab 401K Manual")}

          {/* Cross-book overlap */}
          {overlaps.length > 0 && bookFilter === "all" && (
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-2">Cross-Book Symbol Overlap</h3>
              <div className="flex flex-wrap gap-2">
                {overlaps.slice(0, 10).map((o) => (
                  <span key={o.symbol} className="text-xs bg-vantage-border px-2 py-1 rounded font-mono">
                    {o.symbol} <span className="text-vantage-muted">({o.strategy_ids.length})</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {strategies.length === 0 && <EmptyState icon={Layers} message="No strategies found" />}
        </div>
      )}
    </div>
  );
}
