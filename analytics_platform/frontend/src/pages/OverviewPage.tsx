import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { FreshnessBanner } from "../components/FreshnessBanner";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";
import type { FreshnessRow, TimePoint } from "../types";

function fmtNum(n: number): string {
  return n.toLocaleString("en-US");
}

export function OverviewPage() {
  const overview = usePolling(() => api.overview(), 45_000);
  const timeseries = usePolling(() => api.decisionsTimeseries(), 45_000);
  const freshness = usePolling(() => api.freshness(), 60_000);
  const raec = usePolling(() => api.raecDashboard(), 45_000);
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);

  if (overview.loading || timeseries.loading || freshness.loading) {
    return <LoadingState text="Loading overview..." />;
  }
  if (overview.error) return <ErrorState error={overview.error} />;
  if (timeseries.error) return <ErrorState error={timeseries.error} />;
  if (freshness.error) return <ErrorState error={freshness.error} />;

  const totals = (overview.data?.data.totals ?? {}) as Record<string, number>;
  const points = (timeseries.data?.data.points ?? []) as TimePoint[];
  const freshnessRows = (freshness.data?.data.rows ?? []) as FreshnessRow[];
  const raecStrategies = (raec.data?.data as any)?.summary?.by_strategy ?? [];

  const window = overview.data?.source_window;
  const dateRange =
    window?.date_min && window?.date_max ? `${window.date_min} \u2013 ${window.date_max}` : undefined;

  return (
    <section>
      <h2 className="page-title">Overview</h2>
      {dateRange && <p className="page-subtitle">{dateRange}</p>}
      {!dateRange && <div style={{ marginBottom: 24 }} />}

      {portfolio.data && !portfolio.error && (() => {
        const pData = (portfolio.data.data as Record<string, any>) ?? {};
        const latest = pData.latest ?? {};
        const fmt = (v: number | null) => v != null ? `$${v.toLocaleString(undefined, {maximumFractionDigits: 0})}` : "—";
        return (
          <div className="kpi-grid" style={{ marginBottom: "1.5rem" }}>
            <KpiCard label="Portfolio Capital" value={fmt(latest.capital_total)} />
            <KpiCard label="Net Exposure" value={fmt(latest.net_exposure)} />
            <KpiCard label="Strategies Active" value={(pData.exposure_by_strategy ?? []).length} />
            <KpiCard label="Realized P&L Today" value={fmt(latest.realized_pnl)} />
          </div>
        );
      })()}

      <FreshnessBanner rows={freshnessRows} />

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Use this page as the daily pulse check. Rising <strong>accepted</strong> with stable{" "}
          <strong>gate blocks</strong> usually means execution flow is healthy. If <strong>rejected</strong> or{" "}
          <strong>gate blocks</strong> spike versus recent days, drill into Decisions and S2 Signals to find the
          dominant reason codes and symbols.
        </p>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Decision Cycles" value={fmtNum(totals.cycle_count ?? 0)} />
        <KpiCard label="Intent Rows" value={fmtNum(totals.intent_count ?? 0)} />
        <KpiCard label="Accepted" value={fmtNum(totals.accepted_count ?? 0)} />
        <KpiCard label="Rejected" value={fmtNum(totals.rejected_count ?? 0)} />
        <KpiCard label="Gate Blocks" value={fmtNum(totals.gate_block_count ?? 0)} />
        <KpiCard label="Created Intents" value={fmtNum(totals.created_count ?? 0)} />
      </div>

      <div className="chart-card">
        <h3>Decision + Rejection Trend</h3>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={points} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e4e8da" vertical={false} />
            <XAxis
              dataKey="ny_date"
              tick={{ fontSize: 11, fill: "#8a977d" }}
              tickLine={false}
              axisLine={{ stroke: "#d4dbc6" }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#8a977d" }}
              tickLine={false}
              axisLine={false}
              width={48}
            />
            <Tooltip
              contentStyle={{
                borderRadius: 6,
                border: "1px solid #d4dbc6",
                boxShadow: "0 2px 8px rgba(20,40,10,0.08)",
                fontSize: 13,
              }}
            />
            <Line
              type="monotone"
              dataKey="cycle_count"
              name="Cycles"
              stroke="#2563eb"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="rejected_count"
              name="Rejected"
              stroke="#d97706"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
            <Line
              type="monotone"
              dataKey="accepted_count"
              name="Accepted"
              stroke="#16a34a"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {raec.data && !raec.error && raecStrategies.length > 0 && (
        <div className="table-card">
          <h3>RAEC 401(k) Status</h3>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Regime</th>
                <th>Last Eval</th>
                <th>Rebalances</th>
              </tr>
            </thead>
            <tbody>
              {raecStrategies.map((s: any) => (
                <tr key={s.strategy_id}>
                  <td style={{ fontWeight: 600 }}>{s.strategy_id}</td>
                  <td>
                    <span
                      className={`regime-badge ${s.current_regime?.toLowerCase().replace("_", "-") ?? ""}`}
                    >
                      {s.current_regime ?? "\u2014"}
                    </span>
                  </td>
                  <td className="mono">{s.last_eval_date ?? "\u2014"}</td>
                  <td className="mono">{s.rebalances ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
