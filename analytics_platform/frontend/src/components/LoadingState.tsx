export function LoadingState({ text = "Loading..." }: { text?: string }) {
  return <div className="loading">{text}</div>;
}
