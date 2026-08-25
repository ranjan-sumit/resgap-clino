import type { CountStat } from "@/lib/api";

export function CountStatView({ stat }: { stat: CountStat }) {
  return (
    <div className="group relative overflow-hidden rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
      <div className="absolute inset-x-0 top-0 h-[3px] bg-accent-line opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-neutral">{stat.label}</div>
      <div className="font-display text-clinova-deep text-4xl">{stat.display}</div>
    </div>
  );
}
