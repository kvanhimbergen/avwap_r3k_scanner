import type { LucideIcon } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Layers,
  ShieldAlert,
  ScrollText,
  ScanSearch,
  Crosshair,
  ClipboardList,
  TrendingUp,
  FlaskConical,
  Settings,
  ChevronsLeft,
  ChevronsRight,
} from "../icons";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Command Center", icon: LayoutDashboard, exact: true },
  { to: "/strategies", label: "Strategies", icon: Layers },
  { to: "/risk", label: "Risk", icon: ShieldAlert },
  { to: "/blotter", label: "Blotter", icon: ScrollText },
  { to: "/scan", label: "Scan", icon: ScanSearch },
  { to: "/trade-log", label: "Trade Log", icon: ClipboardList },
  { to: "/execution", label: "Execution", icon: Crosshair },
  { to: "/performance", label: "Performance", icon: TrendingUp },
  { to: "/research", label: "Research", icon: FlaskConical },
];

const BOTTOM_ITEMS: NavItem[] = [
  { to: "/ops", label: "Ops", icon: Settings },
];

export function NavRail({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  const location = useLocation();

  const isActive = (to: string, exact?: boolean) => {
    if (exact) return location.pathname === to;
    return location.pathname.startsWith(to);
  };

  return (
    <nav className="nav-rail">
      {/* Brand */}
      <div className="nav-rail-brand">
        <div className="nav-rail-brand-icon">SC</div>
        <span className="nav-rail-brand-text">Strategy Command</span>
      </div>

      {/* Main nav items */}
      <div className="nav-rail-items">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={`nav-rail-item${isActive(item.to, item.exact) ? " active" : ""}`}
            end={item.exact}
            title={expanded ? undefined : item.label}
          >
            <span className="nav-rail-icon">
              <item.icon size={18} strokeWidth={1.75} />
            </span>
            <span className="nav-rail-label">{item.label}</span>
          </NavLink>
        ))}
      </div>

      {/* Bottom items */}
      <div className="nav-rail-bottom">
        {BOTTOM_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={`nav-rail-item${isActive(item.to) ? " active" : ""}`}
            title={expanded ? undefined : item.label}
          >
            <span className="nav-rail-icon">
              <item.icon size={18} strokeWidth={1.75} />
            </span>
            <span className="nav-rail-label">{item.label}</span>
          </NavLink>
        ))}

        {/* Expand/collapse toggle */}
        <button
          className="nav-rail-toggle"
          onClick={onToggle}
          title={expanded ? "Collapse sidebar" : "Expand sidebar"}
          type="button"
        >
          {expanded
            ? <ChevronsLeft size={16} strokeWidth={1.75} />
            : <ChevronsRight size={16} strokeWidth={1.75} />
          }
        </button>
      </div>
    </nav>
  );
}
