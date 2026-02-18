import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const NAV_SECTIONS = [
  {
    label: "Operations",
    items: [
      { to: "/", label: "Overview" },
      { to: "/decisions", label: "Decisions" },
      { to: "/risk", label: "Risk" },
    ],
  },
  {
    label: "Portfolio",
    items: [
      { to: "/portfolio", label: "Overview" },
      { to: "/strategies/matrix", label: "Strategy Matrix" },
    ],
  },
  {
    label: "AVWAP + S2",
    items: [
      { to: "/strategies", label: "Strategies" },
      { to: "/signals/s2", label: "S2 Signals" },
    ],
  },
  {
    label: "RAEC 401(k)",
    items: [
      { to: "/raec", label: "Dashboard" },
      { to: "/raec/readiness", label: "Readiness" },
      { to: "/raec/log-fills", label: "Log Fills" },
    ],
  },
  {
    label: "Execution",
    items: [
      { to: "/execution/slippage", label: "Slippage" },
      { to: "/analytics/trades", label: "Trade Analytics" },
    ],
  },
  {
    label: "Analysis",
    items: [
      { to: "/journal", label: "Trade Journal" },
      { to: "/pnl", label: "P&L" },
      { to: "/backtests", label: "Backtests" },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/help", label: "Help" },
    ],
  },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div>
          <h1 className="brand">Strategy Ops</h1>
          <p className="brand-sub">AVWAP + S2 Analytics</p>
        </div>
        <nav className="nav-list">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <div className="nav-section-label">{section.label}</div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                  end={item.to === "/"}
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <main className="app-main">{children}</main>
    </div>
  );
}
