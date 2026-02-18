/**
 * Simple tab navigation component.
 */
export function TabGroup({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="tab-group">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`tab${tab.id === active ? " active" : ""}`}
          onClick={() => onChange(tab.id)}
          type="button"
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
