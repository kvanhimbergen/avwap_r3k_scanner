import { NavLink, useLocation } from "react-router-dom";

const NAV_ITEMS = [
  {
    to: "/",
    label: "Command Center",
    icon: "\u2302", // ⌂
    exact: true,
  },
  {
    to: "/strategies",
    label: "Strategies",
    icon: "\u2261", // ≡
  },
  {
    to: "/risk",
    label: "Risk",
    icon: "\u26A0", // ⚠
  },
  {
    to: "/blotter",
    label: "Blotter",
    icon: "\u2630", // ☰
  },
  {
    to: "/execution",
    label: "Execution",
    icon: "\u25CE", // ◎
  },
  {
    to: "/research",
    label: "Research",
    icon: "\uD83D\uDD2C", // 🔬
  },
];

const BOTTOM_ITEMS = [
  {
    to: "/ops",
    label: "Ops",
    icon: "\u2699", // ⚙
  },
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
            <span className="nav-rail-icon">{item.icon}</span>
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
            <span className="nav-rail-icon">{item.icon}</span>
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
          {expanded ? "\u00AB" : "\u00BB"}
        </button>
      </div>
    </nav>
  );
}
