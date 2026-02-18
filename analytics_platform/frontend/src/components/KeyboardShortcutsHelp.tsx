/**
 * Keyboard shortcuts help modal — shown when user presses `?`.
 */
const SHORTCUTS = [
  { keys: ["?"], description: "Toggle this help" },
  { keys: ["g", "h"], description: "Go to Command Center" },
  { keys: ["g", "s"], description: "Go to Strategies" },
  { keys: ["g", "r"], description: "Go to Risk" },
  { keys: ["g", "b"], description: "Go to Blotter" },
  { keys: ["g", "e"], description: "Go to Execution" },
  { keys: ["g", "l"], description: "Go to Log Fills" },
];

export function KeyboardShortcutsHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="kb-overlay" onClick={onClose}>
      <div className="kb-modal" onClick={(e) => e.stopPropagation()}>
        <div className="kb-header">
          <h3 style={{ margin: 0, fontSize: "0.92rem", fontWeight: 700 }}>Keyboard Shortcuts</h3>
          <button className="btn btn-secondary" onClick={onClose} style={{ padding: "2px 8px", fontSize: "0.72rem" }}>
            ESC
          </button>
        </div>
        <div className="kb-list">
          {SHORTCUTS.map((s) => (
            <div key={s.description} className="kb-row">
              <div className="kb-keys">
                {s.keys.map((k, i) => (
                  <span key={i}>
                    {i > 0 && <span className="kb-then">then</span>}
                    <kbd className="kb-key">{k}</kbd>
                  </span>
                ))}
              </div>
              <span className="kb-desc">{s.description}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
