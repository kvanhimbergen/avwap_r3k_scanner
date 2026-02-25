import { AlertTriangle, RefreshCw } from "lucide-react";

interface ErrorStateProps {
  message?: string;
  /** @deprecated Use `message` instead */
  error?: string;
  onRetry?: () => void;
}

export function ErrorState({ message, error, onRetry }: ErrorStateProps) {
  const text = message ?? error ?? "Something went wrong";
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] gap-4 text-vantage-muted">
      <div className="p-4 rounded-full bg-vantage-red/10">
        <AlertTriangle className="w-10 h-10 text-vantage-red" />
      </div>
      <h2 className="text-lg font-semibold text-vantage-text">{text}</h2>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 flex items-center gap-2 px-4 py-2 bg-vantage-blue hover:bg-vantage-blue/80 text-white text-sm rounded-lg transition-colors"
        >
          <RefreshCw size={14} />
          Try Again
        </button>
      )}
    </div>
  );
}
