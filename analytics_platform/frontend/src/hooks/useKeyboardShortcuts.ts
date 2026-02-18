import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

/**
 * Global keyboard shortcuts for quick navigation.
 *
 * Single-key:
 *   ?  → toggle help modal
 *
 * Chord (g + key within 500ms):
 *   g h → Command Center (home)
 *   g s → Strategies
 *   g r → Risk
 *   g b → Blotter
 *   g e → Execution
 *   g l → Log Fills (ops)
 */
export function useKeyboardShortcuts(onToggleHelp: () => void) {
  const navigate = useNavigate();
  const pendingG = useRef(false);
  const timerRef = useRef<number | undefined>();

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Skip when user is typing in an input/textarea/select
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      const key = e.key.toLowerCase();

      if (key === "?") {
        e.preventDefault();
        onToggleHelp();
        return;
      }

      if (pendingG.current) {
        pendingG.current = false;
        window.clearTimeout(timerRef.current);

        const routes: Record<string, string> = {
          h: "/",
          s: "/strategies",
          r: "/risk",
          b: "/blotter",
          e: "/execution",
          l: "/ops/log-fills",
        };

        if (routes[key]) {
          e.preventDefault();
          navigate(routes[key]);
        }
        return;
      }

      if (key === "g") {
        pendingG.current = true;
        timerRef.current = window.setTimeout(() => {
          pendingG.current = false;
        }, 500);
      }
    }

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      window.clearTimeout(timerRef.current);
    };
  }, [navigate, onToggleHelp]);
}
