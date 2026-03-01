import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Layers,
  ArrowUpDown,
  FlaskConical,
  ScrollText,
  TrendingUp,
  ShieldAlert,
  ScanSearch,
  ClipboardList,
  Landmark,
  Settings,
} from "lucide-react";
import { LayoutDataProvider, useLayoutData } from "../context/LayoutDataContext";
import { formatCurrency, pnlColor } from "../lib/format";
import { regimeColor } from "../lib/strategies";

const NAV_ITEMS = [
  { to: "/",            icon: LayoutDashboard, label: "Dashboard" },
  { to: "/strategies",  icon: Layers,          label: "Strategies" },
  { to: "/trade",       icon: ArrowUpDown,     label: "Trade" },
  { to: "/lab",         icon: FlaskConical,    label: "Strategy Lab" },
  { to: "/blotter",     icon: ScrollText,      label: "Blotter" },
  { to: "/performance", icon: TrendingUp,      label: "Performance" },
  { to: "/risk",        icon: ShieldAlert,     label: "Risk" },
  { to: "/scan",        icon: ScanSearch,      label: "Scan" },
  { to: "/trade-log",   icon: ClipboardList,   label: "Trade Log" },
  { to: "/ops/schwab",  icon: Landmark,        label: "Schwab" },
  { to: "/ops/system",  icon: Settings,        label: "System" },
];

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <span className="relative flex h-2.5 w-2.5">
      {connected && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-vantage-green opacity-40" />
      )}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
        connected ? "bg-vantage-green" : "bg-vantage-red"
      }`} />
    </span>
  );
}

export function Layout() {
  return (
    <LayoutDataProvider>
      <LayoutInner />
    </LayoutDataProvider>
  );
}

function LayoutInner() {
  const { portfolio, health, raec } = useLayoutData();

  const latest = (portfolio.data?.data as any)?.latest ?? {};
  const regime = (raec.data?.data as any)?.by_strategy?.[0]?.latest_regime ?? null;
  const connected = !health.error;

  const equity = latest.capital_total as number | undefined;
  const dayPnl = (latest.realized_pnl ?? latest.unrealized_pnl) as number | undefined;

  return (
    <div className="flex h-screen bg-vantage-bg text-vantage-text overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r border-vantage-border flex flex-col bg-vantage-bg">
        {/* Logo */}
        <div className="h-12 flex items-center px-5 border-b border-vantage-border">
          <span className="text-base font-bold tracking-tight">
            <span className="text-vantage-blue">V</span>ANTAGE
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3 px-3 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? "bg-vantage-card text-vantage-text font-medium"
                    : "text-vantage-muted hover:text-vantage-text hover:bg-vantage-card/50"
                }`
              }
            >
              <Icon size={16} strokeWidth={1.75} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Connection status */}
        <div className="border-t border-vantage-border px-4 py-3 flex items-center gap-2">
          <ConnectionDot connected={connected} />
          <span className="text-xs text-vantage-muted">
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-12 shrink-0 border-b border-vantage-border flex items-center justify-between px-5 bg-vantage-bg">
          <div className="flex items-center gap-4">
            <div>
              <p className="text-[11px] text-vantage-muted uppercase tracking-wide">Equity</p>
              <p className="font-mono text-sm font-semibold">
                {equity != null ? formatCurrency(equity, 0) : "\u2014"}
              </p>
            </div>
            <div className="w-px h-5 bg-vantage-border" />
            <div>
              <p className="text-[11px] text-vantage-muted uppercase tracking-wide">Day P&L</p>
              <p className={`font-mono text-sm font-semibold ${pnlColor(dayPnl)}`}>
                {dayPnl != null ? formatCurrency(dayPnl, 0) : "\u2014"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {regime && (
              <span
                className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded"
                style={{
                  backgroundColor: `${regimeColor(regime)}15`,
                  color: regimeColor(regime),
                }}
              >
                {regime}
              </span>
            )}
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wider uppercase border border-vantage-amber/30 bg-vantage-amber/10 text-vantage-amber">
              PAPER
            </span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
