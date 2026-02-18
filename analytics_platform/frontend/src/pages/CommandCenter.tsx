/**
 * Command Center — the home dashboard.
 * Single-screen situational awareness: book P&L, strategy grid, alerts, activity feed.
 */
import { api } from "../api";
import { ActivityFeed, type FeedEvent } from "../components/ActivityFeed";
import { AlertsPanel, type Alert } from "../components/AlertsPanel";
import { bookFromId } from "../components/BookBadge";
import { BookPnlPanel, type BookData } from "../components/BookPnlPanel";
import { LastRefreshed } from "../components/LastRefreshed";
import { SkeletonGrid, SkeletonLoader } from "../components/SkeletonLoader";
import { StrategyStatusCard, type StrategyCardData } from "../components/StrategyStatusCard";
import { usePolling } from "../hooks/usePolling";
import type {
  FreshnessRow,
  JournalRow,
  KeyValue,
  RaecRebalanceEvent,
  ReadinessStrategy,
  StrategyMatrixRow,
} from "../types";

/* ── Strategy metadata for display ──────────────────────── */

interface StrategyMeta {
  shortName: string;
  subtitle: string;
}

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
  // Fuzzy match on common fragments
  for (const [key, val] of Object.entries(META)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  // Fallback: use the raw ID
  return { shortName: id.split("_").pop() ?? id, subtitle: id };
}

/* ── Formatting helpers ─────────────────────────────────── */

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return `${v.toFixed(1)}%`;
}

function fmtTime(ts: string | null | undefined): string {
  if (!ts) return "\u2014";
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "America/New_York" });
  } catch {
    return ts.slice(11, 16);
  }
}

/* ── Health computation ─────────────────────────────────── */

function computeHealth(
  strategyId: string,
  regime: string | null,
  readiness: ReadinessStrategy | undefined,
  freshnessRows: FreshnessRow[],
): "ok" | "warn" | "error" {
  // RISK_OFF → error
  if (regime?.toUpperCase().includes("RISK_OFF")) return "error";

  // Readiness failures
  if (readiness) {
    if (!readiness.state_file_exists) return "error";
    if (readiness.warnings.length > 0) return "warn";
  }

  // Data staleness — check if any source is >4h stale
  const now = Date.now();
  for (const row of freshnessRows) {
    if (!row.latest_mtime_utc) continue;
    const ageH = (now - new Date(row.latest_mtime_utc).getTime()) / 3_600_000;
    if (row.parse_status === "error") return "error";
    if (ageH > 4) return "warn";
  }

  // TRANSITION → warn
  if (regime?.toUpperCase().includes("TRANSITION")) return "warn";

  return "ok";
}

/* ── Data extraction helpers ────────────────────────────── */

function extractStrategies(matrixData: KeyValue | null): StrategyMatrixRow[] {
  if (!matrixData) return [];
  const strats = (matrixData as any).strategies ?? (matrixData as any).rows ?? [];
  return strats as StrategyMatrixRow[];
}

function extractRaecSummary(raecData: KeyValue | null): any[] {
  if (!raecData) return [];
  return (raecData as any)?.summary?.by_strategy ?? [];
}

function extractRaecEvents(raecData: KeyValue | null): RaecRebalanceEvent[] {
  if (!raecData) return [];
  return ((raecData as any)?.events ?? []) as RaecRebalanceEvent[];
}

function extractReadiness(readinessData: KeyValue | null): ReadinessStrategy[] {
  if (!readinessData) return [];
  return ((readinessData as any)?.strategies ?? []) as ReadinessStrategy[];
}

function extractJournal(journalData: KeyValue | null): JournalRow[] {
  if (!journalData) return [];
  return ((journalData as any)?.rows ?? []) as JournalRow[];
}

/* ── Build derived data ─────────────────────────────────── */

function buildBookData(
  strategies: StrategyMatrixRow[],
  portfolioData: KeyValue | null,
  raecSummary: any[],
): { alpaca: BookData; schwab: BookData } {
  const alpacaStrats = strategies.filter((s) => bookFromId(s.strategy_id) === "alpaca");
  const schwabStrats = strategies.filter((s) => bookFromId(s.strategy_id) === "schwab");

  // Portfolio data (primarily for Alpaca — live data)
  const latest = (portfolioData as any)?.latest ?? {};
  const exposureByStrategy: any[] = (portfolioData as any)?.exposure_by_strategy ?? [];

  const alpacaExposure = exposureByStrategy
    .filter((e: any) => bookFromId(e.strategy_id ?? "") === "alpaca")
    .reduce((sum: number, e: any) => sum + (e.notional ?? 0), 0);

  const capitalTotal = latest.capital_total as number | undefined;
  const exposurePct = capitalTotal ? (alpacaExposure / capitalTotal) * 100 : null;

  const alpaca: BookData = {
    title: "ALPACA PAPER",
    subtitle: "AUTO",
    metrics: [
      { label: "Capital", value: fmtUsd(capitalTotal) },
      { label: "Day P&L", value: fmtUsd(latest.realized_pnl ?? latest.unrealized_pnl) },
      { label: "Exposure", value: capitalTotal ? `${fmtUsd(alpacaExposure)} (${fmtPct(exposurePct)})` : "\u2014" },
      { label: "Strategies", value: `${alpacaStrats.length} active` },
    ],
  };

  // Schwab: derived from RAEC data
  const schwabRebalances = raecSummary
    .filter((s: any) => bookFromId(s.strategy_id ?? "") === "schwab")
    .reduce((sum: number, s: any) => sum + (s.rebalances ?? 0), 0);

  const lastEval = raecSummary
    .filter((s: any) => bookFromId(s.strategy_id ?? "") === "schwab")
    .map((s: any) => s.last_eval_date)
    .filter(Boolean)
    .sort()
    .pop();

  const schwab: BookData = {
    title: "SCHWAB 401K",
    subtitle: "MANUAL",
    metrics: [
      { label: "Strategies", value: `${schwabStrats.length} active` },
      { label: "Rebalances", value: String(schwabRebalances) },
      { label: "Last Eval", value: lastEval ?? "\u2014" },
      { label: "Capital", value: "\u2014" },
    ],
  };

  return { alpaca, schwab };
}

function buildStrategyCards(
  strategies: StrategyMatrixRow[],
  raecSummary: any[],
  raecEvents: RaecRebalanceEvent[],
  readinessStrategies: ReadinessStrategy[],
  freshnessRows: FreshnessRow[],
): StrategyCardData[] {
  // Index readiness by strategy_id
  const readinessMap = new Map<string, ReadinessStrategy>();
  for (const r of readinessStrategies) {
    readinessMap.set(r.strategy_id.toUpperCase(), r);
  }

  // Index RAEC summary by strategy_id
  const raecMap = new Map<string, any>();
  for (const s of raecSummary) {
    raecMap.set((s.strategy_id as string).toUpperCase(), s);
  }

  // Build sparkline data from events: count rebalance/trade events by date
  const eventsByStrategy = new Map<string, Map<string, number>>();
  for (const ev of raecEvents) {
    const key = ev.strategy_id.toUpperCase();
    if (!eventsByStrategy.has(key)) eventsByStrategy.set(key, new Map());
    const dateMap = eventsByStrategy.get(key)!;
    dateMap.set(ev.ny_date, (dateMap.get(ev.ny_date) ?? 0) + 1);
  }

  return strategies.map((s) => {
    const upper = s.strategy_id.toUpperCase();
    const meta = getMeta(s.strategy_id);
    const raec = raecMap.get(upper);
    const readiness = readinessMap.get(upper);

    // Regime: prefer RAEC data, fall back to matrix
    const regime = raec?.current_regime ?? s.current_regime ?? null;

    // Health
    const health = computeHealth(s.strategy_id, regime, readiness, freshnessRows);

    // Sparkline: last 14 days of activity
    const dateMap = eventsByStrategy.get(upper);
    let sparkline: number[] = [];
    if (dateMap) {
      const dates = [...dateMap.keys()].sort().slice(-14);
      sparkline = dates.map((d) => dateMap.get(d) ?? 0);
    }
    // If no RAEC events, use trade_count as a single-point
    if (sparkline.length < 2 && s.trade_count > 0) {
      sparkline = [0, s.trade_count];
    }

    // Key metric
    const rebalances = raec?.rebalances ?? 0;
    const isRaec = upper.includes("RAEC");
    const metricValue = isRaec ? rebalances : s.trade_count;
    const metricLabel = isRaec ? "reb" : "trd";

    return {
      strategyId: s.strategy_id,
      shortName: meta.shortName,
      subtitle: meta.subtitle,
      regime,
      health,
      sparklineData: sparkline,
      metricValue,
      metricLabel,
    };
  });
}

function buildAlerts(
  readinessStrategies: ReadinessStrategy[],
  freshnessRows: FreshnessRow[],
  raecSummary: any[],
): Alert[] {
  const alerts: Alert[] = [];

  // Readiness warnings
  for (const r of readinessStrategies) {
    if (!r.state_file_exists) {
      alerts.push({ severity: "error", text: "State file missing", strategyId: r.strategy_id });
    }
    for (const w of r.warnings) {
      alerts.push({ severity: "warn", text: w, strategyId: r.strategy_id });
    }
  }

  // Freshness — stale data sources
  const now = Date.now();
  for (const row of freshnessRows) {
    if (row.parse_status === "error") {
      alerts.push({ severity: "error", text: `Parse error: ${row.source_name}` });
    }
    if (row.latest_mtime_utc) {
      const ageH = (now - new Date(row.latest_mtime_utc).getTime()) / 3_600_000;
      if (ageH > 4) {
        alerts.push({
          severity: "warn",
          text: `${row.source_name} data ${Math.round(ageH)}h stale`,
        });
      }
    }
  }

  // RISK_OFF regimes
  for (const s of raecSummary) {
    const regime = (s.current_regime ?? "") as string;
    if (regime.toUpperCase().includes("RISK_OFF")) {
      alerts.push({
        severity: "warn",
        text: "RISK_OFF regime",
        strategyId: s.strategy_id,
      });
    }
  }

  return alerts;
}

function buildActivityFeed(
  raecEvents: RaecRebalanceEvent[],
  journalRows: JournalRow[],
): FeedEvent[] {
  const events: FeedEvent[] = [];

  // RAEC rebalance events
  for (const ev of raecEvents) {
    if (ev.should_rebalance) {
      events.push({
        time: ev.ny_date,
        type: "rebalance",
        strategyId: getMeta(ev.strategy_id).shortName,
        text: `rebalanced (${ev.intent_count} intent${ev.intent_count !== 1 ? "s" : ""})`,
      });
    }
  }

  // Journal rows (recent trades/fills)
  for (const row of journalRows.slice(0, 30)) {
    events.push({
      time: fmtTime(row.ts_utc) || row.ny_date,
      type: row.posted ? "fill" : "info",
      strategyId: getMeta(row.strategy_id).shortName,
      text: `${row.side} ${row.symbol} ${row.delta_pct > 0 ? "+" : ""}${row.delta_pct.toFixed(1)}%`,
    });
  }

  // Sort by time descending (most recent first)
  events.sort((a, b) => b.time.localeCompare(a.time));

  return events.slice(0, 30);
}

/* ── Command Center Component ───────────────────────────── */

export function CommandCenter() {
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);
  const matrix = usePolling(() => api.strategyMatrix(), 45_000);
  const raec = usePolling(() => api.raecDashboard(), 45_000);
  const readiness = usePolling(() => api.raecReadiness(), 60_000);
  const journal = usePolling(() => api.journal({ limit: 50 }), 45_000);
  const freshness = usePolling(() => api.freshness(), 60_000);

  const isLoading = matrix.loading || raec.loading;
  const error = matrix.error || raec.error;

  // Extract raw data
  const strategies = extractStrategies(matrix.data?.data ?? null);
  const raecSummary = extractRaecSummary(raec.data?.data ?? null);
  const raecEvents = extractRaecEvents(raec.data?.data ?? null);
  const readinessStrategies = extractReadiness(readiness.data?.data ?? null);
  const freshnessRows = (freshness.data?.data?.rows ?? []) as FreshnessRow[];
  const journalRows = extractJournal(journal.data?.data ?? null);

  // Build derived data
  const bookData = buildBookData(strategies, portfolio.data?.data ?? null, raecSummary);
  const strategyCards = buildStrategyCards(strategies, raecSummary, raecEvents, readinessStrategies, freshnessRows);
  const alerts = buildAlerts(readinessStrategies, freshnessRows, raecSummary);
  const feedEvents = buildActivityFeed(raecEvents, journalRows);

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h2 className="page-title">Command Center</h2>
        <LastRefreshed at={matrix.lastRefreshed ?? raec.lastRefreshed} />
      </div>
      <p className="page-subtitle">Portfolio overview and strategy status</p>

      {/* Module 1: Book-Level P&L */}
      {portfolio.loading ? (
        <div className="book-pnl-grid" style={{ marginBottom: 16 }}>
          <SkeletonLoader variant="card" />
          <SkeletonLoader variant="card" />
        </div>
      ) : (
        <BookPnlPanel alpaca={bookData.alpaca} schwab={bookData.schwab} />
      )}

      {/* Module 2: Strategy Status Grid */}
      {isLoading ? (
        <SkeletonGrid count={8} />
      ) : error ? (
        <div className="error-box">{error}</div>
      ) : (
        <div className="strategy-grid">
          {strategyCards.map((card) => (
            <StrategyStatusCard key={card.strategyId} data={card} />
          ))}
          {strategyCards.length === 0 && (
            <div className="empty-state" style={{ gridColumn: "1 / -1" }}>
              No strategies found
            </div>
          )}
        </div>
      )}

      {/* Module 3: Alerts + Activity Feed */}
      <div className="two-col" style={{ marginTop: 16 }}>
        <AlertsPanel alerts={alerts} />
        <ActivityFeed events={feedEvents} />
      </div>
    </section>
  );
}
