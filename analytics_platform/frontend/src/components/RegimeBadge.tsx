/** Normalise a regime string into a CSS class. */
function regimeClass(regime: string | null | undefined): string {
  if (!regime) return "";
  const lower = regime.toLowerCase().replace(/_/g, "-");
  if (lower.includes("risk-on")) return "risk-on";
  if (lower.includes("risk-off")) return "risk-off";
  if (lower.includes("transition")) return "transition";
  return lower;
}

export function RegimeBadge({ regime }: { regime: string | null | undefined }) {
  if (!regime) return <span className="text-tertiary">{"\u2014"}</span>;
  return (
    <span className={`regime-badge ${regimeClass(regime)}`}>{regime}</span>
  );
}
