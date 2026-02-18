import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LastRefreshed } from "../components/LastRefreshed";
import { SkeletonLoader } from "../components/SkeletonLoader";
import { TabGroup } from "../components/TabGroup";
import { usePolling } from "../hooks/usePolling";

const ALL_STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP Core" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
  { id: "RAEC_401K_V1", label: "RAEC V1" },
  { id: "RAEC_401K_V2", label: "RAEC V2" },
  { id: "RAEC_401K_V3", label: "RAEC V3" },
  { id: "RAEC_401K_V4", label: "RAEC V4" },
  { id: "RAEC_401K_V5", label: "RAEC V5" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];

const BUCKET_COLORS: Record<string, string> = {
  mega: "var(--green)",
  large: "var(--blue)",
  mid: "var(--amber)",
  small: "var(--red)",
};

const TABS = [
  { id: "quality", label: "Execution Quality" },
  { id: "activity", label: "Trade Activity" },
];

const TOOLTIP_STYLE = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  fontSize: "0.78rem",
};

const TICK_STYLE = { fill: "var(--text-tertiary)", fontSize: 11 };

/* ── CSV helpers ──────────────────────────────────────────── */

function downloadCsv(filename: string, headers: string[], rows: string[][]) {
  const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportSlippageCsv(data: Record<string, any>) {
  const bySymbol = data.by_symbol ?? [];
  if (bySymbol.length === 0) return;
  downloadCsv(
    `execution-slippage-${new Date().toISOString().slice(0, 10)}.csv`,
    ["Symbol", "Executions", "Mean Slippage (bps)", "Median Slippage (bps)"],
    bySymbol.map((r: any) => [
      r.symbol,
      String(r.count ?? 0),
      (r.mean_bps ?? 0).toFixed(1),
      (r.median_bps ?? 0).toFixed(1),
    ]),
  );
}

function exportActivityCsv(data: Record<string, any>) {
  const perStrategy = data.per_strategy ?? [];
  if (perStrategy.length === 0) return;
  downloadCsv(
    `execution-activity-${new Date().toISOString().slice(0, 10)}.csv`,
    ["Strategy", "Trade Count", "Unique Symbols", "Buys", "Sells", "Buy %"],
    perStrategy.map((r: any) => {
      const total = (r.buys ?? 0) + (r.sells ?? 0);
      const buyPct = total > 0 ? ((r.buys ?? 0) / total * 100).toFixed(1) : "";
      return [r.strategy_id, String(r.trade_count ?? 0), String(r.unique_symbols ?? 0), String(r.buys ?? 0), String(r.sells ?? 0), buyPct];
    }),
  );
}

/* ── Main Component ───────────────────────────────────────── */

export function ExecutionPage() {
  const [tab, setTab] = useState("quality");
  const [strategyId, setStrategyId] = useState("");

  // Both tabs share the strategy filter
  const slippage = usePolling(
    () => api.slippage({ strategy_id: strategyId || undefined }),
    60_000,
  );
  const trades = usePolling(
    () => api.tradeAnalytics({ strategy_id: strategyId || undefined }),
    45_000,
  );

  const slippageData = slippage.data?.data as Record<string, any> ?? {};
  const tradesData = trades.data?.data as Record<string, any> ?? {};

  function handleExportCsv() {
    if (tab === "quality") {
      exportSlippageCsv(slippageData);
    } else {
      exportActivityCsv(tradesData);
    }
  }

  const hasExportData =
    tab === "quality"
      ? (slippageData.by_symbol ?? []).length > 0
      : (tradesData.per_strategy ?? []).length > 0;

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h2 className="page-title">Execution</h2>
          <LastRefreshed at={slippage.lastRefreshed ?? trades.lastRefreshed} />
        </div>
        <button className="btn btn-secondary" onClick={handleExportCsv} disabled={!hasExportData}>
          Export CSV
        </button>
      </div>
      <p className="page-subtitle">Execution quality and trade activity analysis</p>

      {/* Shared Strategy Filter */}
      <div className="filter-bar">
        <label>
          Strategy:{" "}
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            {ALL_STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <TabGroup tabs={TABS} active={tab} onChange={setTab} />

      {tab === "quality" ? (
        <QualityTab slippage={slippage} />
      ) : (
        <ActivityTab trades={trades} />
      )}
    </section>
  );
}

/* ── Execution Quality Tab ───────────────────────────────── */

function QualityTab({ slippage }: { slippage: ReturnType<typeof usePolling<any>> }) {
  if (slippage.loading) return <SkeletonLoader variant="chart" count={3} />;
  if (slippage.error) return <ErrorState error={slippage.error} />;

  const data = slippage.data?.data as Record<string, any> ?? {};
  const summary = data.summary ?? {};
  const byBucket = data.by_bucket ?? [];
  const byTime = data.by_time ?? [];
  const bySymbol = data.by_symbol ?? [];
  const trend = data.trend ?? [];

  const slippageClass = (bps: number) =>
    bps <= 5 ? "slippage-good" : bps <= 15 ? "slippage-warn" : "slippage-bad";

  return (
    <>
      <div className="kpi-grid">
        <KpiCard label="Mean Slippage" value={`${(summary.mean_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="Median Slippage" value={`${(summary.median_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="P95 Slippage" value={`${(summary.p95_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="Total Executions" value={summary.total ?? 0} />
      </div>

      {byBucket.length > 0 && (
        <div className="chart-card">
          <h3>Slippage by Liquidity Bucket</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byBucket}>
              <XAxis dataKey="liquidity_bucket" tick={TICK_STYLE} />
              <YAxis unit=" bps" tick={TICK_STYLE} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar dataKey="mean_bps">
                {byBucket.map((entry: any, idx: number) => (
                  <Cell key={idx} fill={BUCKET_COLORS[entry.liquidity_bucket] ?? "var(--blue)"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {byTime.length > 0 && (
        <div className="chart-card">
          <h3>Slippage by Time of Day</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byTime}>
              <XAxis dataKey="time_of_day_bucket" angle={-45} textAnchor="end" height={80} tick={TICK_STYLE} />
              <YAxis unit=" bps" tick={TICK_STYLE} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar dataKey="mean_bps" fill="var(--purple)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {bySymbol.length > 0 && (
        <div className="table-card">
          <h3>Top Symbols by Absolute Slippage</h3>
          <table>
            <thead>
              <tr><th>Symbol</th><th>Executions</th><th>Mean Slippage (bps)</th></tr>
            </thead>
            <tbody>
              {bySymbol.map((row: any) => (
                <tr key={row.symbol}>
                  <td className="mono">{row.symbol}</td>
                  <td className="mono">{row.count}</td>
                  <td className={slippageClass(Math.abs(row.mean_bps))}>{row.mean_bps.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {trend.length > 0 && (
        <div className="chart-card">
          <h3>Daily Average Slippage Trend</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={trend}>
              <XAxis dataKey="date_ny" tick={TICK_STYLE} />
              <YAxis unit=" bps" tick={TICK_STYLE} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Line type="monotone" dataKey="mean_bps" stroke="var(--blue)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </>
  );
}

/* ── Trade Activity Tab ──────────────────────────────────── */

function ActivityTab({ trades }: { trades: ReturnType<typeof usePolling<any>> }) {
  const data = (trades.data?.data ?? {}) as Record<string, any>;
  const perStrategy = (data.per_strategy ?? []) as Array<Record<string, any>>;
  const dailyFrequency = (data.daily_frequency ?? []) as Array<Record<string, any>>;
  const symbolConcentration = (data.symbol_concentration ?? []) as Array<Record<string, any>>;

  const kpis = useMemo(() => {
    const totalTrades = perStrategy.reduce((s, r) => s + (r.trade_count ?? 0), 0);
    const uniqueSymbols = perStrategy.reduce((s, r) => s + (r.unique_symbols ?? 0), 0);
    const activeStrategies = perStrategy.length;
    const totalBuys = perStrategy.reduce((s, r) => s + (r.buys ?? 0), 0);
    const totalSells = perStrategy.reduce((s, r) => s + (r.sells ?? 0), 0);
    const buySellRatio = totalSells > 0 ? (totalBuys / totalSells).toFixed(2) : "\u2014";
    return { totalTrades, uniqueSymbols, activeStrategies, buySellRatio };
  }, [perStrategy]);

  if (trades.loading) return <SkeletonLoader variant="chart" count={3} />;
  if (trades.error) return <ErrorState error={trades.error} />;

  return (
    <>
      <div className="kpi-grid">
        <KpiCard label="Total Trades" value={kpis.totalTrades} />
        <KpiCard label="Unique Symbols" value={kpis.uniqueSymbols} />
        <KpiCard label="Active Strategies" value={kpis.activeStrategies} />
        <KpiCard label="Buy/Sell Ratio" value={kpis.buySellRatio} />
      </div>

      {dailyFrequency.length > 0 && (
        <div className="chart-card">
          <h3>Daily Trade Frequency</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={dailyFrequency}>
              <XAxis dataKey="ny_date" tick={TICK_STYLE} />
              <YAxis allowDecimals={false} tick={TICK_STYLE} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Line type="monotone" dataKey="count" stroke="var(--blue)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {perStrategy.length > 0 && (
        <div className="table-card">
          <h3>Per-Strategy Breakdown</h3>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Trade Count</th>
                <th>Unique Symbols</th>
                <th>Buys</th>
                <th>Sells</th>
                <th>Buy %</th>
              </tr>
            </thead>
            <tbody>
              {perStrategy.map((row) => {
                const total = (row.buys ?? 0) + (row.sells ?? 0);
                const buyPct = total > 0 ? ((row.buys ?? 0) / total * 100).toFixed(1) : "\u2014";
                return (
                  <tr key={row.strategy_id}>
                    <td style={{ fontWeight: 600 }}>{row.strategy_id}</td>
                    <td className="mono">{row.trade_count}</td>
                    <td className="mono">{row.unique_symbols}</td>
                    <td className="mono side-buy">{row.buys}</td>
                    <td className="mono side-sell">{row.sells}</td>
                    <td className="mono">{buyPct}{buyPct !== "\u2014" ? "%" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {symbolConcentration.length > 0 && (
        <div className="chart-card">
          <h3>Top Symbols by Trade Count</h3>
          <ResponsiveContainer width="100%" height={Math.max(240, symbolConcentration.length * 28)}>
            <BarChart data={symbolConcentration} layout="vertical" margin={{ left: 60 }}>
              <XAxis type="number" allowDecimals={false} tick={TICK_STYLE} />
              <YAxis type="category" dataKey="symbol" width={56} tick={TICK_STYLE} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar dataKey="count" fill="var(--blue)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </>
  );
}
