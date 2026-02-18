export function KpiCard({
  label,
  value,
  subtext,
  delta,
  deltaDirection,
}: {
  label: string;
  value: string | number;
  subtext?: string;
  delta?: string;
  deltaDirection?: "positive" | "negative" | "neutral";
}) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {delta && (
        <div className={`kpi-delta ${deltaDirection ?? "neutral"}`}>
          {deltaDirection === "positive" && "\u25B2 "}
          {deltaDirection === "negative" && "\u25BC "}
          {delta}
        </div>
      )}
      {subtext ? <div className="kpi-subtext">{subtext}</div> : null}
    </div>
  );
}
