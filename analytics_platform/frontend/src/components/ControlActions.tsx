/**
 * ControlActions — placeholder strategy lifecycle buttons.
 * Future: pause/resume, adjust weight, emergency kill switch.
 * Currently disabled with tooltip explaining future functionality.
 */
export function ControlActions({ strategyId }: { strategyId: string }) {
  return (
    <div className="control-actions">
      <button
        className="btn btn-secondary control-btn"
        disabled
        title="Pause strategy execution (coming soon)"
      >
        Pause
      </button>
      <button
        className="btn btn-secondary control-btn"
        disabled
        title="Adjust strategy weight allocation (coming soon)"
      >
        Adjust Weight
      </button>
      <button
        className="btn btn-danger control-btn"
        disabled
        title="Emergency kill switch — halt all activity (coming soon)"
      >
        Kill Switch
      </button>
    </div>
  );
}
