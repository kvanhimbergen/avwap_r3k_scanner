import { useState } from "react";
import { api } from "../api";
import { usePolling } from "../hooks/usePolling";
import { StatusDot } from "./StatusDot";
import type { StatusLevel } from "./StatusDot";
import type { FreshnessRow } from "../types";

/** Compute overall system health from freshness sources. */
function computeSystemHealth(rows: FreshnessRow[]): { level: StatusLevel; label: string } {
  if (rows.length === 0) return { level: "neutral", label: "No data" };

  const now = Date.now();
  let warnings = 0;
  let errors = 0;

  for (const row of rows) {
    if (row.parse_status === "error" || row.last_error) {
      errors++;
    } else if (row.latest_mtime_utc) {
      const age = now - new Date(row.latest_mtime_utc).getTime();
      const hours = age / (1000 * 60 * 60);
      if (hours > 4) errors++;
      else if (hours > 2) warnings++;
    }
  }

  if (errors > 0) return { level: "error", label: `${errors} source${errors > 1 ? "s" : ""} degraded` };
  if (warnings > 0) return { level: "warn", label: `${warnings} warning${warnings > 1 ? "s" : ""}` };
  return { level: "ok", label: "All systems nominal" };
}

/** Extract latest regime label from risk controls. */
function extractRegime(riskData: Record<string, any> | null): string | null {
  if (!riskData) return null;
  const regimes = (riskData.regimes ?? []) as Array<Record<string, unknown>>;
  if (regimes.length === 0) return null;
  const latest = regimes[regimes.length - 1];
  return String(latest.regime_label ?? latest.regime_id ?? "");
}

function regimeClass(regime: string): string {
  const upper = regime.toUpperCase();
  if (upper === "RISK_ON") return "risk-on";
  if (upper === "RISK_OFF" || upper === "STRESSED") return "risk-off";
  if (upper === "NEUTRAL" || upper === "TRANSITION" || upper === "DATA_GAP") return "transition";
  return "";
}

export function RegimeStrip() {
  const freshness = usePolling(() => api.freshness(), 60_000);
  const risk = usePolling(() => api.riskControls(), 60_000);
  const [showPopover, setShowPopover] = useState(false);

  const freshnessRows = (freshness.data?.data?.rows ?? []) as FreshnessRow[];
  const health = computeSystemHealth(freshnessRows);
  const riskData = (risk.data?.data ?? null) as Record<string, any> | null;
  const regime = extractRegime(riskData);

  const now = new Date();
  const dateStr = now.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const lastRefresh = freshness.data?.as_of_utc
    ? new Date(freshness.data.as_of_utc).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        timeZoneName: "short",
      })
    : null;

  return (
    <div className="regime-strip">
      {/* Regime */}
      {regime && (
        <>
          <div className="regime-strip-section">
            <span className="text-tertiary" style={{ fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Regime
            </span>
            <span className={`regime-badge ${regimeClass(regime)}`}>{regime}</span>
          </div>
          <div className="regime-strip-divider" />
        </>
      )}

      {/* Last refresh */}
      {lastRefresh && (
        <>
          <div className="regime-strip-section">
            <span className="text-tertiary" style={{ fontSize: "0.68rem" }}>Last refresh:</span>
            <span className="font-mono" style={{ fontSize: "0.72rem", color: "var(--text-secondary)" }}>
              {lastRefresh}
            </span>
          </div>
          <div className="regime-strip-divider" />
        </>
      )}

      {/* System health (right-aligned) */}
      <div className="regime-strip-right">
        <div
          className="regime-strip-section"
          style={{ cursor: "pointer", position: "relative" }}
          onClick={() => setShowPopover(!showPopover)}
        >
          <StatusDot status={health.level} />
          <span style={{ color: health.level === "ok" ? "var(--green)" : health.level === "warn" ? "var(--amber)" : "var(--red)", fontSize: "0.72rem", fontWeight: 600 }}>
            {health.label}
          </span>

          {/* Freshness popover */}
          {showPopover && freshnessRows.length > 0 && (
            <div className="popover" onClick={(e) => e.stopPropagation()}>
              <div style={{ fontWeight: 600, marginBottom: 8, fontSize: "0.75rem", color: "var(--text)" }}>
                Data Sources
              </div>
              {freshnessRows.map((row) => {
                const age = row.latest_mtime_utc
                  ? Math.round((Date.now() - new Date(row.latest_mtime_utc).getTime()) / (1000 * 60))
                  : null;
                const level: StatusLevel = row.last_error ? "error" : age != null && age > 240 ? "error" : age != null && age > 120 ? "warn" : "ok";
                return (
                  <div key={row.source_name} className="popover-row">
                    <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <StatusDot status={level} />
                      <span style={{ color: "var(--text-secondary)" }}>{row.source_name}</span>
                    </span>
                    <span className="font-mono" style={{ color: "var(--text-tertiary)", fontSize: "0.68rem" }}>
                      {age != null ? `${age}m ago` : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="regime-strip-divider" />
        <span style={{ fontSize: "0.72rem", color: "var(--text-tertiary)" }}>{dateStr}</span>
      </div>
    </div>
  );
}
