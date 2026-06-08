import type { DataFreshness } from "../types";

interface ConfidenceFooterProps {
  freshness?: DataFreshness | null;
  className?: string;
}

function todayNY(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

function bdaysSince(dateStr: string | null): number | null {
  if (!dateStr) return null;
  try {
    const today = new Date(`${todayNY()}T00:00:00-05:00`);
    const then = new Date(`${dateStr}T00:00:00-05:00`);
    const calendarDays = Math.floor((+today - +then) / 86_400_000);
    if (calendarDays <= 0) return 0;
    // Rough business-day approximation: weekends are 2/7 of calendar days.
    return Math.max(0, Math.round(calendarDays * 5 / 7));
  } catch {
    return null;
  }
}

type DotStatus = "ok" | "warn" | "alert";

interface FreshnessDot {
  label: string;
  detail: string;
  status: DotStatus;
}

const DOT_BG: Record<DotStatus, string> = {
  ok: "bg-vantage-green",
  warn: "bg-vantage-amber",
  alert: "bg-vantage-red",
};

function feedStatus(dateStr: string | null, warnDays: number, alertDays: number, label: string): FreshnessDot {
  const age = bdaysSince(dateStr);
  if (age == null) return { label, detail: "no data", status: "alert" };
  if (age >= alertDays) return { label, detail: `${age} bday stale`, status: "alert" };
  if (age >= warnDays) return { label, detail: `${age} bday stale`, status: "warn" };
  return { label, detail: dateStr ?? "ok", status: "ok" };
}

function tokenStatus(days: number, healthy: boolean): FreshnessDot {
  if (!healthy) return { label: "Schwab token", detail: "unhealthy", status: "alert" };
  if (days < 1) return { label: "Schwab token", detail: `${days.toFixed(1)}d to expiry`, status: "alert" };
  if (days < 2) return { label: "Schwab token", detail: `${days.toFixed(1)}d to expiry`, status: "warn" };
  return { label: "Schwab token", detail: `${days.toFixed(1)}d to expiry`, status: "ok" };
}

/**
 * The "system being honest about what it doesn't know" surface. Pairs a
 * confidence rating (sample size, live track record, hedge activations)
 * with feed-freshness dots so the user can see immediately whether any
 * underlying data is going stale before the pipeline notices.
 */
export function ConfidenceFooter({ freshness, className }: ConfidenceFooterProps) {
  const containerClass = `bg-vantage-card border border-vantage-border rounded-lg p-4 ${className ?? ""}`;

  const dots: FreshnessDot[] = freshness
    ? [
        feedStatus(freshness.regime_e1, 2, 5, "E1 regime"),
        feedStatus(freshness.schwab_snapshot, 2, 5, "Schwab snapshot"),
        feedStatus(freshness.coordinator, 2, 5, "Coordinator"),
        feedStatus(freshness.scan_output, 2, 5, "Scan output"),
        tokenStatus(freshness.token_health?.days_until_expiry ?? 0, freshness.token_health?.healthy ?? false),
      ]
    : [];

  const anyAlert = dots.some((d) => d.status === "alert");
  const anyWarn = dots.some((d) => d.status === "warn");
  const overallTone = anyAlert ? "alert" : anyWarn ? "warn" : "ok";

  return (
    <div className={containerClass}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">Confidence & freshness</h3>
        <span className="text-[10px] font-mono text-vantage-muted">
          {overallTone === "ok" ? "all feeds fresh" : overallTone === "warn" ? "1+ feed warning" : "1+ feed alert"}
        </span>
      </div>

      {/* Honest framing — sample size, live track record */}
      <ul className="text-xs space-y-1.5 mb-3">
        <li className="flex gap-2">
          <span className="text-vantage-green">●</span>
          <span className="text-vantage-muted">
            Strategy backtested 2018–2026 (1 cycle incl. 2020 + 2022) — see {" "}
            <span className="underline-offset-2">backtest output</span>.
          </span>
        </li>
        <li className="flex gap-2">
          <span className="text-vantage-amber">●</span>
          <span className="text-vantage-muted">
            Live track record: 6 months, 1 regime change. Confidence accrues with cycles, not months.
          </span>
        </li>
        <li className="flex gap-2">
          <span className="text-vantage-muted">○</span>
          <span className="text-vantage-muted">
            Hedge activated in real money: 0 times yet — protection is theoretical until exercised.
          </span>
        </li>
      </ul>

      {/* Freshness dots */}
      {dots.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-2 pt-3 border-t border-vantage-border">
          {dots.map((d) => (
            <div key={d.label} className="flex items-center gap-1.5 text-[11px]">
              <span className={`w-2 h-2 rounded-full inline-block ${DOT_BG[d.status]}`} />
              <span className="text-vantage-text">{d.label}</span>
              <span className="text-vantage-muted font-mono">{d.detail}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
