import { useMemo, useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
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

export function TradeAnalyticsPage() {
  const [strategyId, setStrategyId] = useState("");
  const trades = usePolling(
    () => api.tradeAnalytics({ strategy_id: strategyId || undefined }),
    45_000,
  );

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

  if (trades.loading) return <LoadingState text="Loading trade analytics..." />;
  if (trades.error) return <ErrorState error={trades.error} />;

  return (
    <section>
      <h2 className="page-title">Trade Analytics</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This page shows trade activity across all strategies. Use it to understand which strategies
          are most active, which symbols are traded most frequently, and whether trading activity is
          increasing or decreasing over time.
        </p>
      </div>

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

      <div className="kpi-grid">
        <KpiCard label="Total Trades" value={kpis.totalTrades} />
        <KpiCard label="Unique Symbols" value={kpis.uniqueSymbols} />
        <KpiCard label="Active Strategies" value={kpis.activeStrategies} />
        <KpiCard label="Buy/Sell Ratio" value={kpis.buySellRatio} />
      </div>

      {/* Daily Trade Frequency */}
      {dailyFrequency.length > 0 && (
        <div className="chart-card">
          <h3>Daily Trade Frequency</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={dailyFrequency}>
              <XAxis dataKey="ny_date" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#1f6feb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Per-Strategy Breakdown */}
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
                    <td className="mono" style={{ color: "#0f9d58" }}>{row.buys}</td>
                    <td className="mono" style={{ color: "#d93025" }}>{row.sells}</td>
                    <td className="mono">{buyPct}{buyPct !== "\u2014" ? "%" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Symbol Concentration */}
      {symbolConcentration.length > 0 && (
        <div className="chart-card">
          <h3>Top Symbols by Trade Count</h3>
          <ResponsiveContainer width="100%" height={Math.max(240, symbolConcentration.length * 28)}>
            <BarChart data={symbolConcentration} layout="vertical" margin={{ left: 60 }}>
              <XAxis type="number" allowDecimals={false} />
              <YAxis type="category" dataKey="symbol" width={56} />
              <Tooltip />
              <Bar dataKey="count" fill="#1f6feb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
