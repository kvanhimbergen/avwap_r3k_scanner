/**
 * Strategy Roster — book-grouped strategy listing at /strategies.
 * Groups strategies by book (Alpaca vs Schwab), with book-level summary headers,
 * sort/filter controls, and cross-book symbol overlap analysis.
 */
import { useState } from "react";

import { api } from "../api";
import { bookFromId } from "../components/BookBadge";
import { SkeletonLoader } from "../components/SkeletonLoader";
import { StrategyRosterCard, type RosterCardData } from "../components/StrategyRosterCard";
import { usePolling } from "../hooks/usePolling";
import type {
  FreshnessRow,
  KeyValue,
  RaecRebalanceEvent,
  ReadinessStrategy,
  StrategyMatrixRow,
  SymbolOverlap,
} from "../types";

/* ── Strategy metadata ──────────────────────────────────── */

interface StrategyMeta { shortName: string; subtitle: string }

const META: Record<string, StrategyMeta> = {
  S1_AVWAP_CORE: { shortName: "S1", subtitle: "AVWAP" },
  S2_LETF_ORB_AGGRO: { shortName: "S2", subtitle: "LETF ORB" },
  RAEC_401K_V1: { shortName: "V1", subtitle: "Core" },
  RAEC_401K_V2: { shortName: "V2", subtitle: "Enhanced" },
  RAEC_401K_V3: { shortName: "V3", subtitle: "Aggressive" },
  RAEC_401K_V4: { shortName: "V4", subtitle: "Macro" },
  RAEC_401K_V5: { shortName: "V5", subtitle: "AI/Tech" },
  RAEC_401K_COORD: { shortName: "COORD", subtitle: "40/30/30" },
};

function getMeta(id: string): StrategyMeta {
  const upper = id.toUpperCase();
  if (META[upper]) return META[upper];
  for (const [key, val] of Object.entries(META)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  return { shortName: id.split("_").pop() ?? id, subtitle: id };
}

/* ── Sort options ────────────────────────────────────────── */

type SortKey = "activity" | "regime" | "exposure" | "trades";

function sortCards(cards: RosterCardData[], key: SortKey): RosterCardData[] {
  const sorted = [...cards];
  switch (key) {
    case "activity":
      return sorted.sort((a, b) => (b.rebalances ?? b.trades) - (a.rebalances ?? a.trades));
    case "regime":
      return sorted.sort((a, b) => (a.regime ?? "").localeCompare(b.regime ?? ""));
    case "trades":
      return sorted.sort((a, b) => b.trades - a.trades);
    case "exposure":
    default:
      return sorted;
  }
}

/* ── Data extraction ─────────────────────────────────────── */

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
  return ((data as any).overlaps ?? []) as SymbolOverlap[];
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

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

/* ── Build roster cards ──────────────────────────────────── */

function buildCards(
  strategies: StrategyMatrixRow[],
  raecSummary: any[],
  raecEvents: RaecRebalanceEvent[],
  readinessStrategies: ReadinessStrategy[],
  freshnessRows: FreshnessRow[],
  portfolioData: KeyValue | null,
): RosterCardData[] {
  const readinessMap = new Map<string, ReadinessStrategy>();
  for (const r of readinessStrategies) readinessMap.set(r.strategy_id.toUpperCase(), r);

  const raecMap = new Map<string, any>();
  for (const s of raecSummary) raecMap.set((s.strategy_id as string).toUpperCase(), s);

  const eventsByStrategy = new Map<string, Map<string, number>>();
  for (const ev of raecEvents) {
    const key = ev.strategy_id.toUpperCase();
    if (!eventsByStrategy.has(key)) eventsByStrategy.set(key, new Map());
    const dateMap = eventsByStrategy.get(key)!;
    dateMap.set(ev.ny_date, (dateMap.get(ev.ny_date) ?? 0) + 1);
  }

  // Portfolio exposure by strategy
  const exposureByStrategy: any[] = (portfolioData as any)?.exposure_by_strategy ?? [];
  const capitalTotal = (portfolioData as any)?.latest?.capital_total as number | undefined;

  return strategies.map((s) => {
    const upper = s.strategy_id.toUpperCase();
    const meta = getMeta(s.strategy_id);
    const raec = raecMap.get(upper);
    const readiness = readinessMap.get(upper);
    const regime = raec?.latest_regime ?? s.latest_regime ?? null;
    const health = computeHealth(regime, readiness, freshnessRows);
    const book = bookFromId(s.strategy_id);
    const isAlpaca = book === "alpaca";
    const isCoord = upper.includes("COORD");

    // Sparkline
    const dateMap = eventsByStrategy.get(upper);
    let sparkline: number[] = [];
    if (dateMap) {
      const dates = [...dateMap.keys()].sort().slice(-14);
      sparkline = dates.map((d) => dateMap.get(d) ?? 0);
    }
    if (sparkline.length < 2 && s.trade_count > 0) sparkline = [0, s.trade_count];

    // Exposure (Alpaca only)
    let exposure: string | undefined;
    if (isAlpaca && capitalTotal) {
      const exp = exposureByStrategy
        .filter((e: any) => e.strategy_id?.toUpperCase() === upper)
        .reduce((sum: number, e: any) => sum + (e.notional ?? 0), 0);
      if (exp) exposure = `${fmtUsd(exp)} (${((exp / capitalTotal) * 100).toFixed(0)}%)`;
    }

    return {
      strategyId: s.strategy_id,
      shortName: meta.shortName,
      subtitle: meta.subtitle,
      regime,
      health,
      sparklineData: sparkline,
      trades: s.trade_count,
      uniqueSymbols: s.unique_symbols,
      exposure,
      rebalances: raec?.rebalances,
      isCompact: !isAlpaca && !isCoord,
    };
  });
}

/* ── Component ──────────────────────────────────────────── */

export function StrategyRoster() {
  const [sortKey, setSortKey] = useState<SortKey>("activity");
  const [bookFilter, setBookFilter] = useState<"all" | "alpaca" | "schwab">("all");

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

  const allCards = buildCards(
    strategies, raecSummary, raecEvents, readinessStrategies, freshnessRows, portfolio.data?.data ?? null,
  );

  const filtered = bookFilter === "all"
    ? allCards
    : allCards.filter((c) => bookFromId(c.strategyId) === bookFilter);

  const alpacaCards = sortCards(filtered.filter((c) => bookFromId(c.strategyId) === "alpaca"), sortKey);
  const schwabCards = sortCards(filtered.filter((c) => bookFromId(c.strategyId) === "schwab"), sortKey);

  // Book-level summaries
  const alpacaRebalances = raecSummary
    .filter((s: any) => bookFromId(s.strategy_id ?? "") === "alpaca")
    .reduce((sum: number, s: any) => sum + (s.rebalances ?? 0), 0);
  const schwabRebalances = raecSummary
    .filter((s: any) => bookFromId(s.strategy_id ?? "") === "schwab")
    .reduce((sum: number, s: any) => sum + (s.rebalances ?? 0), 0);

  const capitalTotal = (portfolio.data?.data as any)?.latest?.capital_total as number | undefined;

  return (
    <section>
      <h2 className="page-title">Strategies</h2>
      <p className="page-subtitle">Strategy roster grouped by book</p>

      {/* ── Filters ─────────────────────────────────────── */}
      <div className="filter-bar">
        <label>
          Sort:
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="activity">Activity</option>
            <option value="regime">Regime</option>
            <option value="trades">Trades</option>
          </select>
        </label>
        <label>
          Filter:
          <select value={bookFilter} onChange={(e) => setBookFilter(e.target.value as any)}>
            <option value="all">All Books</option>
            <option value="alpaca">Alpaca Paper</option>
            <option value="schwab">Schwab 401K</option>
          </select>
        </label>
      </div>

      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SkeletonLoader variant="card" />
          <SkeletonLoader variant="card" />
          <SkeletonLoader variant="card" />
        </div>
      ) : error ? (
        <div className="error-box">{error}</div>
      ) : (
        <>
          {/* ── Alpaca Paper (Automated) ───────────────────── */}
          {(bookFilter === "all" || bookFilter === "alpaca") && alpacaCards.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div className="roster-book-header">
                <span className="roster-book-title">Alpaca Paper</span>
                <span className="book-badge alpaca">AUTO</span>
                <span className="roster-book-summary">
                  {capitalTotal ? `Capital: ${fmtUsd(capitalTotal)}` : ""}
                  {alpacaRebalances > 0 ? ` \u00B7 ${alpacaRebalances} reb` : ""}
                </span>
              </div>
              <div className="roster-grid roster-grid-wide">
                {alpacaCards.map((card) => (
                  <StrategyRosterCard key={card.strategyId} data={card} />
                ))}
              </div>
            </div>
          )}

          {/* ── Schwab 401K (Manual) ──────────────────────── */}
          {(bookFilter === "all" || bookFilter === "schwab") && schwabCards.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div className="roster-book-header">
                <span className="roster-book-title">Schwab 401K Manual</span>
                <span className="book-badge schwab">MANUAL</span>
                <span className="roster-book-summary">
                  {schwabRebalances > 0 ? `${schwabRebalances} rebalances` : ""}
                </span>
              </div>
              <div className="roster-grid">
                {schwabCards.map((card) => (
                  <StrategyRosterCard key={card.strategyId} data={card} />
                ))}
              </div>
            </div>
          )}

          {/* ── Cross-Book Analysis ──────────────────────── */}
          {overlaps.length > 0 && bookFilter === "all" && (
            <div className="table-card">
              <h3>Cross-Book Analysis</h3>
              <div className="text-secondary" style={{ fontSize: "0.78rem" }}>
                Symbol Overlap:{" "}
                {overlaps.slice(0, 10).map((o, i) => (
                  <span key={o.symbol}>
                    {i > 0 && " \u00B7 "}
                    <span className="overlap-highlight">
                      {o.symbol} ({o.strategy_ids.length} strategies)
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {filtered.length === 0 && (
            <div className="empty-state">No strategies match the current filter</div>
          )}
        </>
      )}
    </section>
  );
}
