import { api } from "../api";
import { StatusDot } from "../components/StatusDot";
import { usePolling } from "../hooks/usePolling";
import type { FreshnessRow } from "../types";

function freshnessStatus(row: FreshnessRow): "ok" | "warn" | "error" {
  if (row.parse_status === "error" || row.last_error) return "error";
  if (!row.latest_mtime_utc) return "warn";
  const age = Date.now() - new Date(row.latest_mtime_utc).getTime();
  const hours = age / (1000 * 60 * 60);
  if (hours > 24) return "error";
  if (hours > 6) return "warn";
  return "ok";
}

function relativeAge(utc: string | null): string {
  if (!utc) return "—";
  const age = Date.now() - new Date(utc).getTime();
  const mins = Math.floor(age / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function SystemPage() {
  const freshness = usePolling(() => api.freshness(), 60_000);
  const health = usePolling(() => api.health(), 60_000);

  const freshnessRows = (freshness.data?.data.rows ?? []) as FreshnessRow[];
  const healthData = (health.data?.data ?? {}) as Record<string, unknown>;

  return (
    <section>
      <h2 className="page-title">System & Operations</h2>
      <p className="page-subtitle">Data freshness, workflow guide, and troubleshooting</p>

      {/* Data Source Freshness */}
      <div className="table-card">
        <h3>Data Source Freshness</h3>
        {freshness.loading ? (
          <div className="loading">Loading freshness data...</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Source</th>
                <th>Files</th>
                <th>Rows</th>
                <th>Last Updated</th>
                <th>Parse</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {freshnessRows.map((row) => (
                <tr key={row.source_name}>
                  <td><StatusDot status={freshnessStatus(row)} /></td>
                  <td style={{ fontWeight: 600 }}>{row.source_name}</td>
                  <td className="mono">{row.file_count}</td>
                  <td className="mono">{row.row_count.toLocaleString()}</td>
                  <td className="mono">{relativeAge(row.latest_mtime_utc)}</td>
                  <td>
                    <span className={row.parse_status === "ok" ? "text-green" : "text-red"}>
                      {row.parse_status}
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: "0.72rem", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {row.last_error ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* System Health */}
      <div className="table-card">
        <h3>System Health</h3>
        {health.loading ? (
          <div className="loading">Loading...</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
            {Object.entries(healthData).map(([key, val]) => (
              <div key={key}>
                <div className="kpi-label">{key}</div>
                <div className="mono" style={{ fontSize: "0.85rem", color: "var(--text)" }}>{String(val)}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Workflow Guide */}
      <div className="helper-card" style={{ marginTop: 16 }}>
        <h3 className="helper-title">Daily Workflow (10-15 min)</h3>
        <ol style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: "0.78rem", color: "var(--text-secondary)", lineHeight: 1.8 }}>
          <li>Open <strong>Command Center</strong> to confirm system pulse and book-level P&L.</li>
          <li>Check <strong>Risk Monitor</strong> for throttle events and regime changes.</li>
          <li>Review <strong>Strategy Roster</strong> for any amber/red strategy cards.</li>
          <li>Open <strong>Blotter</strong> to verify today&apos;s trades look correct.</li>
          <li>If RAEC 401k fills need logging, go to <strong>Ops &gt; Log Fills</strong>.</li>
        </ol>
      </div>

      <div className="two-col" style={{ marginTop: 16 }}>
        {/* Page Reference */}
        <div className="table-card">
          <h3>Page Reference</h3>
          <table>
            <thead>
              <tr>
                <th>Page</th>
                <th>Purpose</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>Command Center</td><td>System health, book P&L, strategy statuses, alerts</td></tr>
              <tr><td>Strategies</td><td>Book-grouped strategy roster with health indicators</td></tr>
              <tr><td>Strategy Tearsheet</td><td>Deep-dive on a single strategy (allocations, signals, blotter)</td></tr>
              <tr><td>Risk Monitor</td><td>Regime, throttle events, exposure, decision pipeline, drift</td></tr>
              <tr><td>Blotter</td><td>Unified trade journal filterable by book/strategy/symbol/side</td></tr>
              <tr><td>Execution</td><td>Slippage analysis + trade activity patterns</td></tr>
              <tr><td>Research / Backtests</td><td>Backtest runs, equity curves, metric comparison</td></tr>
              <tr><td>Research / Signals</td><td>S2 signal audit (eligibility, selection, reason codes)</td></tr>
              <tr><td>Ops / Log Fills</td><td>Manual Schwab 401k fill entry form</td></tr>
            </tbody>
          </table>
        </div>

        {/* Troubleshooting */}
        <div className="table-card">
          <h3>Troubleshooting</h3>
          <table>
            <thead>
              <tr>
                <th>Symptom</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Blank or stale charts</td>
                <td>Check freshness table above. Verify API health endpoint returns OK.</td>
              </tr>
              <tr>
                <td>Missing S2 rows</td>
                <td>Confirm STRATEGY_SIGNALS files exist for the expected date.</td>
              </tr>
              <tr>
                <td>No recent decisions</td>
                <td>Verify execution/runtime ledgers are being written.</td>
              </tr>
              <tr>
                <td>Low acceptance suddenly</td>
                <td>Inspect Risk Monitor first, then reason codes in Research &gt; Signals.</td>
              </tr>
              <tr>
                <td>Regime stuck</td>
                <td>Check freshness of regime data source. Stale data = stale regime.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Weekly Review */}
      <div className="helper-card" style={{ marginTop: 16 }}>
        <h3 className="helper-title">Weekly Review Routine</h3>
        <ol style={{ margin: "8px 0 0", paddingLeft: 20, fontSize: "0.78rem", color: "var(--text-secondary)", lineHeight: 1.8 }}>
          <li>Review <strong>Execution</strong> tab for slippage trends and symbol concentration.</li>
          <li>Check <strong>Strategy Roster</strong> for any strategies with persistent warnings.</li>
          <li>Compare regime history in <strong>Risk Monitor</strong> to understand throttle periods.</li>
          <li>Run backtests in <strong>Research</strong> if parameter changes are being considered.</li>
          <li>Make one controlled parameter change at most; monitor next week.</li>
        </ol>
      </div>
    </section>
  );
}
