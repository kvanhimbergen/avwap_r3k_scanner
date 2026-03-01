import { useState, useEffect, useCallback, type ReactNode } from "react";
import { KeyboardShortcutsHelp } from "./KeyboardShortcutsHelp";
import { NavRail } from "./NavRail";
import { RegimeStrip } from "./RegimeStrip";
import { useKeyboardShortcuts } from "../hooks/useKeyboardShortcuts";

const STORAGE_KEY = "nav-expanded";

export function AppShell({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });

  const [showHelp, setShowHelp] = useState(false);
  const toggleHelp = useCallback(() => setShowHelp((v) => !v), []);

  useKeyboardShortcuts(toggleHelp);

  // Close help on Escape
  useEffect(() => {
    if (!showHelp) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setShowHelp(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showHelp]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(expanded));
    } catch {
      // ignore
    }
  }, [expanded]);

  return (
    <div className={`app-shell${expanded ? " nav-expanded" : ""}`}>
      <RegimeStrip />
      <NavRail expanded={expanded} onToggle={() => setExpanded(!expanded)} />
      <main className="app-main">{children}</main>
      {showHelp && <KeyboardShortcutsHelp onClose={() => setShowHelp(false)} />}
    </div>
  );
}
