/** Strategy metadata and book classification utilities. */

export interface StrategyMeta {
  shortName: string;
  subtitle: string;
  type: "s1" | "s2" | "raec" | "coord";
  color: string;
}

const META: Record<string, StrategyMeta> = {
  S1_AVWAP_CORE:      { shortName: "S1",    subtitle: "AVWAP Core",          type: "s1",    color: "#10b981" },
  S2_LETF_ORB_AGGRO:  { shortName: "S2",    subtitle: "LETF ORB Aggro",     type: "s2",    color: "#3b82f6" },
  RAEC_401K_V1:       { shortName: "V1",    subtitle: "Core",               type: "raec",  color: "#f59e0b" },
  RAEC_401K_V2:       { shortName: "V2",    subtitle: "Enhanced",           type: "raec",  color: "#8b5cf6" },
  RAEC_401K_V3:       { shortName: "V3",    subtitle: "Aggressive",         type: "raec",  color: "#ef4444" },
  RAEC_401K_V4:       { shortName: "V4",    subtitle: "Macro",              type: "raec",  color: "#06b6d4" },
  RAEC_401K_V5:       { shortName: "V5",    subtitle: "AI/Tech",            type: "raec",  color: "#f97316" },
  RAEC_401K_COORD:    { shortName: "COORD", subtitle: "40/30/30 Coordinator", type: "coord", color: "#14b8a6" },
};

export function getMeta(id: string): StrategyMeta {
  const upper = id.toUpperCase();
  if (META[upper]) return META[upper];
  for (const [key, val] of Object.entries(META)) {
    if (upper.includes(key) || key.includes(upper)) return val;
  }
  const isS = upper.startsWith("S1") || upper.startsWith("S2");
  return { shortName: id.split("_").pop() ?? id, subtitle: id, type: isS ? "s1" : "raec", color: "#9ca3af" };
}

/** Derive the book from a strategy ID. */
export function bookFromId(strategyId: string, backendBookId?: string | null): "alpaca" | "schwab" {
  if (backendBookId === "ALPACA_PAPER") return "alpaca";
  if (backendBookId === "SCHWAB_401K_MANUAL") return "schwab";
  const id = strategyId.toUpperCase();
  if (id.startsWith("S1") || id.startsWith("S2")) return "alpaca";
  if (id.includes("_V1") || id.endsWith("V1")) return "alpaca";
  if (id.includes("_V2") || id.endsWith("V2")) return "alpaca";
  return "schwab";
}

export const REGIME_COLORS: Record<string, string> = {
  RISK_ON: "#10b981",
  TRENDING_UP: "#10b981",
  RISK_OFF: "#ef4444",
  TRENDING_DOWN: "#ef4444",
  TRANSITION: "#f59e0b",
  NEUTRAL: "#9ca3af",
};

export function regimeColor(regime: string | null): string {
  if (!regime) return "#9ca3af";
  const upper = regime.toUpperCase().replace(/\s+/g, "_");
  return REGIME_COLORS[upper] ?? "#9ca3af";
}
