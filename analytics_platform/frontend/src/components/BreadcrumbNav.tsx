import { Link } from "react-router-dom";

export interface Crumb {
  label: string;
  to?: string;
}

export function BreadcrumbNav({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="breadcrumbs">
      {crumbs.map((crumb, i) => (
        <span key={crumb.label}>
          {i > 0 && <span className="breadcrumbs-separator">{" / "}</span>}
          {crumb.to ? (
            <Link to={crumb.to}>{crumb.label}</Link>
          ) : (
            <span style={{ color: "var(--text)" }}>{crumb.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
