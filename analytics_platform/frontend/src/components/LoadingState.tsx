import { Loader2 } from "lucide-react";

export function LoadingState({ text = "Loading..." }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-12 gap-3 text-vantage-muted">
      <Loader2 size={16} className="animate-spin" />
      <span className="text-sm">{text}</span>
    </div>
  );
}
