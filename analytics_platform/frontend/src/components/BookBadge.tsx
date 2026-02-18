/** Derive the book from a strategy ID.
 *  S1/S2 (scan) + V1/V2 (RAEC) → ALPACA_PAPER (automated)
 *  V3/V4/V5/COORD (RAEC)       → SCHWAB_401K_MANUAL
 */
export function bookFromId(strategyId: string): "alpaca" | "schwab" {
  const id = strategyId.toUpperCase();
  if (id.startsWith("S1") || id.startsWith("S2")) return "alpaca";
  if (id.includes("_V1") || id.endsWith("V1")) return "alpaca";
  if (id.includes("_V2") || id.endsWith("V2")) return "alpaca";
  return "schwab";
}

const LABELS: Record<string, string> = {
  alpaca: "ALP",
  schwab: "SCH",
};

export function BookBadge({ strategyId }: { strategyId: string }) {
  const book = bookFromId(strategyId);
  return <span className={`book-badge ${book}`}>{LABELS[book]}</span>;
}
