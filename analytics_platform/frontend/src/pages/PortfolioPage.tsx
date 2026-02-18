import { PieChart, Pie, Cell, LineChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const STRATEGY_COLORS: Record<string, string> = {
  S1_AVWAP_CORE: "#1f6feb",
  S2_LETF_ORB_AGGRO: "#8b5cf6",
  RAEC_401K_V1: "#0f9d58",
  RAEC_401K_V2: "#34a853",
  RAEC_401K_V3: "#dd6b20",
  RAEC_401K_V4: "#db4437",
  RAEC_401K_V5: "#f4b400",
  RAEC_401K_COORD: "#4285f4",
};

export function PortfolioPage() {
  const overview = usePolling(() => api.portfolioOverview({}), 60_000);

  if (overview.loading) return <LoadingState text="Loading portfolio data..." />;
  if (overview.error) return <ErrorState error={overview.error} />;

  const data = overview.data?.data as Record<string, any> ?? {};
  const latest = data.latest ?? {};
  const positions = data.positions ?? [];
  const exposureByStrategy = data.exposure_by_strategy ?? [];
  const history = data.history ?? [];

  const formatCurrency = (val: number | null) =>
    val != null ? `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";

  return (
    <section>
      <h2 className="page-title">Portfolio Overview</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          This page shows your <strong>unified portfolio</strong> across all strategies.
          Monitor <strong>capital utilization</strong> (cash vs. invested),
          <strong> gross/net exposure</strong>, and <strong>P&amp;L</strong> to ensure
          the portfolio is operating within risk bounds.
        </p>
      </div>

      {/* Capital KPIs */}
      <div className="kpi-grid">
        <KpiCard label="Total Capital" value={formatCurrency(latest.capital_total)} />
        <KpiCard label="Cash" value={formatCurrency(latest.capital_cash)} />
        <KpiCard label="Invested" value={formatCurrency(latest.capital_invested)} />
        <KpiCard label="Gross Exposure" value={formatCurrency(latest.gross_exposure)} />
        <KpiCard label="Net Exposure" value={formatCurrency(latest.net_exposure)} />
      </div>

      {/* P&L KPIs */}
      <div className="kpi-grid">
        <KpiCard label="Realized P&L (Today)" value={formatCurrency(latest.realized_pnl)} />
        <KpiCard label="Unrealized P&L" value={formatCurrency(latest.unrealized_pnl)} />
        <KpiCard label="Fees (Today)" value={formatCurrency(latest.fees_today)} />
      </div>

      {/* Exposure by Strategy pie chart */}
      {exposureByStrategy.length > 0 && (
        <div className="chart-card">
          <h3>Exposure by Strategy</h3>
          <div className="pie-card">
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={exposureByStrategy}
                  dataKey="notional"
                  nameKey="strategy_id"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={({ strategy_id, notional }: { strategy_id: string; notional: number }) => `${strategy_id}: ${(notional / 1000).toFixed(0)}k`}
                >
                  {exposureByStrategy.map((entry: any, idx: number) => (
                    <Cell key={idx} fill={STRATEGY_COLORS[entry.strategy_id] ?? "#999"} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Capital over time */}
      {history.length > 0 && (
        <div className="chart-card">
          <h3>Capital & Exposure Over Time</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={history}>
              <XAxis dataKey="date_ny" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="capital_total" stroke="#1f6feb" strokeWidth={2} name="Capital" dot={false} />
              <Line type="monotone" dataKey="gross_exposure" stroke="#dd6b20" strokeWidth={1.5} name="Gross Exposure" dot={false} />
              <Line type="monotone" dataKey="net_exposure" stroke="#0f9d58" strokeWidth={1.5} name="Net Exposure" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Position table */}
      {positions.length > 0 && (
        <div className="table-card">
          <h3>All Positions ({latest.date_ny})</h3>
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Avg Price</th>
                <th>Mark Price</th>
                <th>Notional</th>
                <th>Weight</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any, idx: number) => (
                <tr key={idx}>
                  <td>{p.strategy_id}</td>
                  <td><strong>{p.symbol}</strong></td>
                  <td>{p.qty}</td>
                  <td>{p.avg_price != null ? `$${p.avg_price.toFixed(2)}` : "—"}</td>
                  <td>{p.mark_price != null ? `$${p.mark_price.toFixed(2)}` : "—"}</td>
                  <td>{formatCurrency(p.notional)}</td>
                  <td>
                    {p.weight_pct != null ? `${p.weight_pct.toFixed(1)}%` : "—"}
                    <div className="weight-bar" style={{ width: `${Math.min(p.weight_pct ?? 0, 100)}%` }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
