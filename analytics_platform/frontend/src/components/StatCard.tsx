import { pnlColor } from "../lib/format";

interface StatCardProps {
  label: string;
  value: string;
  numericValue?: number | null;
  subtitle?: string;
}

export function StatCard({ label, value, numericValue, subtitle }: StatCardProps) {
  const colorClass = numericValue != null ? pnlColor(numericValue) : "text-vantage-text";
  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 min-w-0">
      <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">{label}</p>
      <p className={`font-mono text-2xl font-bold ${colorClass}`}>{value}</p>
      {subtitle && <p className="text-[10px] text-vantage-muted mt-1">{subtitle}</p>}
    </div>
  );
}
