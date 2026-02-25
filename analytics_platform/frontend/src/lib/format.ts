/** Currency — "$1,234.56" */
export function formatCurrency(value: number | null | undefined, decimals = 2): string {
  if (value == null) return "\u2014";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** Percent — "+12.34%" (with sign prefix) */
export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null) return "\u2014";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(decimals)}%`;
}

/** Number — "1,234.56" */
export function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value == null) return "\u2014";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/** P&L color class */
export function pnlColor(value: number | null | undefined): string {
  if (value == null) return "text-vantage-muted";
  if (value > 0) return "text-vantage-green";
  if (value < 0) return "text-vantage-red";
  return "text-vantage-muted";
}

/** Score color hex */
export function scoreColor(score: number): string {
  if (score >= 70) return "#10b981";
  if (score >= 40) return "#f59e0b";
  return "#ef4444";
}

/** Compact USD — "$25K" */
export function fmtUsdCompact(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  if (Math.abs(v) >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

/** Time ago string */
export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "\u2014";
  const ms = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "< 1h ago";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
