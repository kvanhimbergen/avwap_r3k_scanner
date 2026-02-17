import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { to: "/", label: "Overview" },
  { to: "/strategies", label: "Strategies" },
  { to: "/signals/s2", label: "S2 Signals" },
  { to: "/decisions", label: "Decisions" },
  { to: "/risk", label: "Risk" },
  { to: "/backtests", label: "Backtests" },
  { to: "/help", label: "Help" },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <h1 className="brand">Strategy Ops</h1>
        <p className="brand-sub">AVWAP + S2 Analytics</p>
        <nav className="nav-list">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              end={item.to === "/"}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="app-main">{children}</main>
    </div>
  );
}
