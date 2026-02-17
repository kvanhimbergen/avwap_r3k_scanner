export function ErrorState({ error }: { error: string }) {
  return <div className="error-box">{error}</div>;
}
