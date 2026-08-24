import type { CountStat } from "@/lib/api";

export function CountStatView({ stat }: { stat: CountStat }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5 shadow-card">
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">{stat.label}</div>
      <div className="font-display text-3xl text-clinova-deep">{stat.display}</div>
    </div>
  );
}
