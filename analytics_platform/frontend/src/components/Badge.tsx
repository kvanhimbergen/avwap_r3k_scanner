import { regimeColor } from "../lib/strategies";

type BadgeVariant = "active" | "disabled" | "warning" | "error" | "info" | "ai" | "evaluating";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  active:     "bg-vantage-green/15 text-vantage-green",
  disabled:   "bg-vantage-muted/10 text-vantage-muted",
  warning:    "bg-vantage-amber/15 text-vantage-amber",
  error:      "bg-vantage-red/15 text-vantage-red",
  info:       "bg-vantage-blue/15 text-vantage-blue",
  ai:         "bg-purple-500/20 text-purple-400",
  evaluating: "bg-cyan-500/20 text-cyan-400",
};

export function StatusBadge({ variant, children }: { variant: BadgeVariant; children: React.ReactNode }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${VARIANT_CLASSES[variant]}`}>
      {children}
    </span>
  );
}

export function RegimeBadge({ regime }: { regime: string | null }) {
  if (!regime) return null;
  const color = regimeColor(regime);
  return (
    <span
      className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded"
      style={{ backgroundColor: `${color}15`, color }}
    >
      {regime}
    </span>
  );
}

export function BookBadge({ book }: { book: "alpaca" | "schwab" }) {
  const isAlpaca = book === "alpaca";
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
      isAlpaca ? "bg-vantage-amber/15 text-vantage-amber" : "bg-vantage-blue/15 text-vantage-blue"
    }`}>
      {isAlpaca ? "AUTO" : "MANUAL"}
    </span>
  );
}

export function CountBadge({ count }: { count: number }) {
  return (
    <span className="text-[9px] px-1 py-0.5 rounded-full font-mono bg-vantage-border text-vantage-muted">
      {count}
    </span>
  );
}
