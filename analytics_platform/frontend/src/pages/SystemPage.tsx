/**
 * System — /ops/system
 * Data freshness, system health, workflow guide, troubleshooting.
 */
import { Settings, CheckCircle, AlertTriangle, XCircle } from "lucide-react";

import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { SkeletonTable } from "../components/Skeleton";
import { useLayoutData } from "../context/LayoutDataContext";
import { usePolling } from "../hooks/usePolling";
import type { FreshnessRow } from "../types";

function freshnessStatus(row: FreshnessRow): "ok" | "warn" | "error" {
  if (row.parse_status === "error" || row.last_error) return "error";
  if (!row.latest_mtime_utc) return "warn";
  const hours = (Date.now() - new Date(row.latest_mtime_utc).getTime()) / 3_600_000;
  if (hours > 24) return "error";
  if (hours > 6) return "warn";
  return "ok";
}

function relativeAge(utc: string | null): string {
  if (!utc) return "\u2014";
  const mins = Math.floor((Date.now() - new Date(utc).getTime()) / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const STATUS_ICON = {
  ok: <CheckCircle size={14} className="text-vantage-green" />,
  warn: <AlertTriangle size={14} className="text-vantage-amber" />,
  error: <XCircle size={14} className="text-vantage-red" />,
};

const STATUS_BADGE = { ok: "active", warn: "warning", error: "error" } as const;

export function SystemPage() {
  const { health } = useLayoutData();
  const freshness = usePolling(() => api.freshness(), 60_000);

  const freshnessRows = (freshness.data?.data?.rows ?? []) as FreshnessRow[];
  const healthData = (health.data?.data ?? {}) as Record<string, unknown>;

  return (
    <div className="space-y-6 max-w-[1200px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Settings size={24} className="text-vantage-muted" />
        <div>
          <h2 className="text-xl font-semibold">System & Operations</h2>
          <p className="text-[11px] text-vantage-muted">Data freshness, workflow guide, and troubleshooting</p>
        </div>
      </div>

      {/* Data Source Freshness */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3">Data Source Freshness</h3>
        {freshness.loading ? (
          <SkeletonTable />
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-vantage-border">
              <th className="py-2 px-2 text-left text-vantage-muted font-medium w-8"></th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Source</th>
              <th className="py-2 px-2 text-right text-vantage-muted font-medium">Files</th>
              <th className="py-2 px-2 text-right text-vantage-muted font-medium">Rows</th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Last Updated</th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Parse</th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Error</th>
            </tr></thead>
            <tbody>
              {freshnessRows.map((row) => {
                const status = freshnessStatus(row);
                return (
                  <tr key={row.source_name} className="border-b border-vantage-border/50">
                    <td className="py-2 px-2">{STATUS_ICON[status]}</td>
                    <td className="py-2 px-2 font-semibold">{row.source_name}</td>
                    <td className="py-2 px-2 font-mono text-right">{row.file_count}</td>
                    <td className="py-2 px-2 font-mono text-right">{row.row_count.toLocaleString()}</td>
                    <td className="py-2 px-2 font-mono">{relativeAge(row.latest_mtime_utc)}</td>
                    <td className="py-2 px-2">
                      <StatusBadge variant={STATUS_BADGE[row.parse_status === "ok" ? "ok" : "error"]}>
                        {row.parse_status}
                      </StatusBadge>
                    </td>
                    <td className="py-2 px-2 font-mono text-vantage-muted max-w-[200px] truncate">{row.last_error ?? "\u2014"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* System Health */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3">System Health</h3>
        {health.loading ? (
          <p className="text-xs text-vantage-muted">Loading...</p>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Object.entries(healthData).map(([key, val]) => (
              <div key={key}>
                <p className="text-[10px] text-vantage-muted uppercase tracking-wide">{key}</p>
                <p className="font-mono text-sm font-semibold">{String(val)}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Workflow Guide */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg">
        <div className="p-4 border-b border-vantage-border">
          <h3 className="text-sm font-semibold">Daily Workflow (10-15 min)</h3>
        </div>
        <div className="p-4">
          <ol className="list-decimal list-inside space-y-2 text-xs text-vantage-muted">
            <li>Open <span className="text-vantage-text font-medium">Command Center</span> to confirm system pulse and book-level P&L.</li>
            <li>Check <span className="text-vantage-text font-medium">Risk Monitor</span> for throttle events and regime changes.</li>
            <li>Review <span className="text-vantage-text font-medium">Strategies</span> for any amber/red strategy cards.</li>
            <li>Open <span className="text-vantage-text font-medium">Blotter</span> to verify today's trades look correct.</li>
            <li>Check <span className="text-vantage-text font-medium">Schwab Account</span> for live positions and reconciliation.</li>
          </ol>
        </div>
      </div>

      {/* Troubleshooting */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Page Reference</h3>
          <table className="w-full text-xs">
            <tbody>
              {[
                ["Command Center", "System health, book P&L, strategy statuses, alerts"],
                ["Strategies", "Book-grouped strategy roster with health indicators"],
                ["Strategy Lab", "AI-powered strategy experimentation"],
                ["Blotter", "Unified trade journal"],
                ["Performance", "Portfolio metrics and benchmarking"],
                ["Risk Monitor", "Regime, throttle events, exposure, decision pipeline"],
                ["Scan", "AVWAP R3K daily scan candidates"],
                ["Schwab Account", "Live 401(k) positions and reconciliation"],
              ].map(([page, desc]) => (
                <tr key={page} className="border-b border-vantage-border/50">
                  <td className="py-2 font-semibold">{page}</td>
                  <td className="py-2 text-vantage-muted">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Troubleshooting</h3>
          <table className="w-full text-xs">
            <tbody>
              {[
                ["Blank/stale charts", "Check freshness table. Verify API health."],
                ["Missing S2 rows", "Confirm STRATEGY_SIGNALS files exist."],
                ["No recent decisions", "Verify execution/runtime ledgers are written."],
                ["Low acceptance", "Inspect Risk Monitor, then reason codes."],
                ["Regime stuck", "Check freshness of regime data source."],
              ].map(([symptom, action]) => (
                <tr key={symptom} className="border-b border-vantage-border/50">
                  <td className="py-2 font-semibold text-vantage-amber">{symptom}</td>
                  <td className="py-2 text-vantage-muted">{action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
