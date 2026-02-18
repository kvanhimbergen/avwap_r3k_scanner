/**
 * Aggregated alerts panel — warnings sorted by severity.
 * Sources: readiness check failures, stale data, RISK_OFF regimes, allocation drift.
 */

export interface Alert {
  severity: "error" | "warn" | "info";
  text: string;
  strategyId?: string;
}

const SEVERITY_ORDER: Record<string, number> = { error: 0, warn: 1, info: 2 };
const SEVERITY_ICON: Record<string, string> = { error: "\u2716", warn: "\u26A0", info: "\u25CF" };

export function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  const sorted = [...alerts].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  );

  const errorCount = alerts.filter((a) => a.severity === "error").length;
  const warnCount = alerts.filter((a) => a.severity === "warn").length;

  return (
    <div className="data-card">
      <h3 style={{ margin: "0 0 8px", fontSize: "0.82rem", fontWeight: 600, color: "var(--text)" }}>
        Alerts
      </h3>
      {sorted.length === 0 ? (
        <div className="empty-state" style={{ padding: "16px 0" }}>
          <div style={{ fontSize: "0.78rem", color: "var(--text-tertiary)" }}>No active alerts</div>
        </div>
      ) : (
        <div className="alerts-panel">
          {sorted.map((alert, i) => (
            <div key={i} className="alert-item">
              <span className={`alert-icon ${alert.severity}`}>
                {SEVERITY_ICON[alert.severity]}
              </span>
              <span className="alert-text">
                {alert.strategyId && (
                  <span className="font-mono font-bold" style={{ marginRight: 4 }}>
                    {alert.strategyId}:
                  </span>
                )}
                {alert.text}
              </span>
            </div>
          ))}
          <div className="alert-count">
            {errorCount} critical / {warnCount} warning{warnCount !== 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}
