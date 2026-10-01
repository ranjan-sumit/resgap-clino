export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "Not recorded";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}
