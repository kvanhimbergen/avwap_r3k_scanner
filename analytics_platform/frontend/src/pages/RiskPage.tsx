import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
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
import { SummaryStrip } from "../components/SummaryStrip";
import { usePolling } from "../hooks/usePolling";
import type { TimePoint } from "../types";

export function RiskPage() {
  const risk = usePolling(() => api.riskControls(), 60_000);
  const decisions = usePolling(() => api.decisionsTimeseries(), 60_000);
  const pnl = usePolling(() => api.pnl(), 60_000);
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);

  if (risk.error) return <ErrorState error={risk.error} />;

  const controls = (risk.data?.data?.risk_controls ?? []) as Array<Record<string, unknown>>;
  const regimes = (risk.data?.data?.regimes ?? []) as Array<Record<string, unknown>>;
  const decisionPoints = (decisions.data?.data?.points ?? []) as TimePoint[];
  const pnlData = (pnl.data?.data as Record<string, any>) ?? {};
  const allocationDrift: any[] = pnlData.allocation_drift ?? [];
  const byStrategy: any[] = pnlData.by_strategy ?? [];
  const portfolioData = (portfolio.data?.data as Record<string, any>) ?? {};

  // Compute risk summary KPIs
  const latestControl = controls[0] as Record<string, any> | undefined;
  const latestRegime = regimes[0] as Record<string, any> | undefined;
  const totalRebalances = byStrategy.reduce((sum: number, s: any) => sum + (s.rebalance_count ?? 0), 0);
  const totalRegimeChanges = byStrategy.reduce((sum: number, s: any) => sum + (s.regime_changes ?? 0), 0);

  // Decision funnel
  const decisionTotals = useMemo(() => {
    const cycles = decisionPoints.reduce((s, p) => s + p.cycle_count, 0);
    const intents = decisionPoints.reduce((s, p) => s + p.intent_count, 0);
    const accepted = decisionPoints.reduce((s, p) => s + p.accepted_count, 0);
    const rejected = decisionPoints.reduce((s, p) => s + p.rejected_count, 0);
    const gates = decisionPoints.reduce((s, p) => s + p.gate_blocks, 0);
    return { cycles, intents, accepted, rejected, gates };
  }, [decisionPoints]);

  const avgDrift = useMemo(() => {
    if (allocationDrift.length === 0) return "—";
    const avg = allocationDrift.reduce((s: number, d: any) => s + (d.drift ?? 0), 0) / allocationDrift.length;
    return `${avg.toFixed(1)}%`;
  }, [allocationDrift]);

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h2 className="page-title">Risk Monitor</h2>
        <LastRefreshed at={risk.lastRefreshed} />
      </div>
      <p className="page-subtitle">Regime, exposure, throttle events, and decision pipeline</p>

      {/* Risk Summary KPIs */}
      {risk.loading ? (
        <SkeletonLoader variant="card" count={1} />
      ) : (
        <div className="kpi-grid">
          <KpiCard
            label="Current Regime"
            value={String(latestRegime?.regime_id ?? "—")}
          />
          <KpiCard
            label="Risk Multiplier"
            value={latestControl?.risk_multiplier != null ? String(latestControl.risk_multiplier) : "—"}
          />
          <KpiCard
            label="Max Positions"
            value={latestControl?.max_positions != null ? String(latestControl.max_positions) : "—"}
          />
          <KpiCard label="Avg Drift" value={avgDrift} />
        </div>
      )}

      {/* Regime Timeline */}
      <div className="table-card">
        <h3>Regime Timeline</h3>
        {risk.loading ? (
          <SkeletonLoader variant="chart" />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Regime</th>
                <th>Reasons</th>
              </tr>
            </thead>
            <tbody>
              {regimes.map((row, idx) => (
                <tr key={`${row.ny_date}-${row.regime_id}-${idx}`}>
                  <td className="mono">{String(row.ny_date ?? "")}</td>
                  <td>
                    <span
                      className={`regime-badge ${
                        row.regime_id === "RISK_ON"
                          ? "risk-on"
                          : row.regime_id === "RISK_OFF"
                            ? "risk-off"
                            : "transition"
                      }`}
                    >
                      {String(row.regime_id ?? "")}
                    </span>
                  </td>
                  <td className="mono">{String(row.reason_codes_json ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="two-col">
        {/* Risk Control Events */}
        <div className="table-card">
          <h3>Risk Control Events</h3>
          {risk.loading ? (
            <SkeletonLoader variant="chart" />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Source</th>
                  <th>Risk Mult.</th>
                  <th>Max Pos.</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {controls.map((row, idx) => (
                  <tr key={`${row.source_type}-${row.as_of_utc}-${idx}`}>
                    <td className="mono">{String(row.ny_date ?? "")}</td>
                    <td>{String(row.source_type ?? "")}</td>
                    <td className="mono">{String(row.risk_multiplier ?? "")}</td>
                    <td className="mono">{String(row.max_positions ?? "")}</td>
                    <td>{String(row.throttle_reason ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Exposure Utilization */}
        <div className="table-card">
          <h3>Exposure Summary</h3>
          {portfolio.loading ? (
            <SkeletonLoader variant="card" count={3} />
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
                <div>
                  <div className="kpi-label">Gross Exposure</div>
                  <div className="kpi-value" style={{ fontSize: "1.1rem" }}>
                    {portfolioData.gross_exposure != null
                      ? `$${Number(portfolioData.gross_exposure).toLocaleString()}`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="kpi-label">Net Exposure</div>
                  <div className="kpi-value" style={{ fontSize: "1.1rem" }}>
                    {portfolioData.net_exposure != null
                      ? `$${Number(portfolioData.net_exposure).toLocaleString()}`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="kpi-label">Capital Total</div>
                  <div className="kpi-value" style={{ fontSize: "1.1rem" }}>
                    {portfolioData.capital_total != null
                      ? `$${Number(portfolioData.capital_total).toLocaleString()}`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="kpi-label">Cash Available</div>
                  <div className="kpi-value" style={{ fontSize: "1.1rem" }}>
                    {portfolioData.capital_cash != null
                      ? `$${Number(portfolioData.capital_cash).toLocaleString()}`
                      : "—"}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Allocation Drift Over Time */}
      {pnl.loading ? (
        <div className="chart-card" style={{ marginTop: 16 }}>
          <h3>Allocation Drift Over Time</h3>
          <SkeletonLoader variant="chart" />
        </div>
      ) : (
        allocationDrift.length > 0 && (
          <div className="chart-card">
            <h3>Allocation Drift Over Time</h3>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={allocationDrift}>
                <XAxis dataKey="ny_date" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
                <YAxis unit="%" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    fontSize: "0.78rem",
                  }}
                />
                <Line type="monotone" dataKey="drift" stroke="var(--amber)" strokeWidth={2} dot={false} name="Drift %" />
                <Line type="monotone" dataKey="target_total" stroke="var(--green)" strokeWidth={1.5} dot={false} name="Target %" />
                <Line type="monotone" dataKey="current_total" stroke="var(--blue)" strokeWidth={1.5} dot={false} name="Current %" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )
      )}

      {/* Decision Pipeline */}
      <div className="chart-card">
        <h3>Decision Pipeline</h3>
        {decisions.loading ? (
          <SkeletonLoader variant="chart" />
        ) : (
          <>
            <SummaryStrip
              items={[
                { label: "Cycles", value: decisionTotals.cycles },
                { label: "Intents", value: decisionTotals.intents },
                { label: "Accepted", value: decisionTotals.accepted },
                { label: "Rejected", value: decisionTotals.rejected },
                { label: "Gate Blocks", value: decisionTotals.gates },
              ]}
            />
            {decisionPoints.length > 0 && (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={decisionPoints}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="ny_date" tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
                  <YAxis tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      background: "var(--surface-raised)",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      fontSize: "0.78rem",
                    }}
                  />
                  <Bar dataKey="cycle_count" fill="var(--blue)" name="Cycles" />
                  <Bar dataKey="accepted_count" fill="var(--green)" name="Accepted" />
                  <Bar dataKey="rejected_count" fill="var(--amber)" name="Rejected" />
                  <Bar dataKey="gate_blocks" fill="var(--red)" name="Gate Blocks" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </>
        )}
      </div>

      {/* Rebalance Frequency by Strategy */}
      {byStrategy.length > 0 && (
        <div className="chart-card">
          <h3>Rebalance Frequency by Strategy</h3>
          <SummaryStrip
            items={[
              { label: "Total Rebalances", value: totalRebalances },
              { label: "Regime Changes", value: totalRegimeChanges },
              { label: "Strategies", value: byStrategy.length },
            ]}
          />
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={byStrategy}>
              <XAxis dataKey="strategy_id" tick={{ fill: "var(--text-tertiary)", fontSize: 10 }} />
              <YAxis tick={{ fill: "var(--text-tertiary)", fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontSize: "0.78rem",
                }}
              />
              <Bar dataKey="rebalance_count" fill="var(--blue)" name="Rebalances" />
              <Bar dataKey="regime_changes" fill="var(--amber)" name="Regime Changes" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
