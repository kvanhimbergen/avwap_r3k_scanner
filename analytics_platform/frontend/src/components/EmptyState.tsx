import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  message?: string;
}

export function EmptyState({ icon: Icon, message = "No data available" }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-vantage-muted">
      {Icon && <Icon size={24} className="mb-2 opacity-40" />}
      <p className="text-sm">{message}</p>
    </div>
  );
}
