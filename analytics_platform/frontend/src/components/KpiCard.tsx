import { TrendingUp, TrendingDown } from "../icons";

export function KpiCard({
  label,
  value,
  unit,
  subtext,
  delta,
  deltaDirection,
}: {
  label: string;
  value: string | number;
  unit?: string;
  subtext?: string;
  delta?: string;
  deltaDirection?: "positive" | "negative" | "neutral";
}) {
  const sentimentClass = delta && deltaDirection && deltaDirection !== "neutral"
    ? deltaDirection
    : "";

  return (
    <div className={`kpi-card ${sentimentClass}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
      {delta && (
        <div className={`kpi-delta ${deltaDirection ?? "neutral"}`}>
          {deltaDirection === "positive" && <TrendingUp size={12} strokeWidth={2} style={{ marginRight: 2 }} />}
          {deltaDirection === "negative" && <TrendingDown size={12} strokeWidth={2} style={{ marginRight: 2 }} />}
          {delta}
        </div>
      )}
      {subtext ? <div className="kpi-subtext">{subtext}</div> : null}
    </div>
  );
}
