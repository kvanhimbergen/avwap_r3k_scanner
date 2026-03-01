/**
 * Aggregated alerts panel — warnings sorted by severity.
 * Sources: readiness check failures, stale data, RISK_OFF regimes, allocation drift.
 */
import { AlertCircle, AlertTriangle, Info } from "../icons";

export interface Alert {
  severity: "error" | "warn" | "info";
  text: string;
  strategyId?: string;
}

const SEVERITY_ORDER: Record<string, number> = { error: 0, warn: 1, info: 2 };

const SEVERITY_ICON = {
  error: AlertCircle,
  warn: AlertTriangle,
  info: Info,
} as const;

export function AlertsPanel({ alerts }: { alerts: Alert[] }) {
  const sorted = [...alerts].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  );

  const errorCount = alerts.filter((a) => a.severity === "error").length;
  const warnCount = alerts.filter((a) => a.severity === "warn").length;

  return (
    <div className="data-card">
      <div className="section-header">
        <h3 className="section-header-title">Alerts</h3>
        {alerts.length > 0 && (
          <span className="section-header-count">{alerts.length}</span>
        )}
      </div>
      {sorted.length === 0 ? (
        <div className="empty-state" style={{ padding: "16px 0" }}>
          <div style={{ fontSize: "0.78rem", color: "var(--text-tertiary)" }}>No active alerts</div>
        </div>
      ) : (
        <div className="alerts-panel">
          {sorted.map((alert, i) => {
            const Icon = SEVERITY_ICON[alert.severity];
            return (
              <div key={i} className="alert-item">
                <span className={`alert-icon ${alert.severity}`}>
                  <Icon size={14} strokeWidth={2} />
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
            );
          })}
          <div className="alert-count">
            {errorCount} critical / {warnCount} warning{warnCount !== 1 ? "s" : ""}
          </div>
        </div>
      )}
    </div>
  );
}
