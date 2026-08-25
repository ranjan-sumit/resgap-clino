import type { ResearchCouncilView } from "@/lib/api";

// A real ranked bar list -- which input parameters the simulation is most
// sensitive to -- instead of a bare importance number in a table cell.
export function SensitivityBars({ drivers }: { drivers: ResearchCouncilView["sensitivity_ranking"] }) {
  if (drivers.length === 0) return null;
  const max = Math.max(...drivers.map((d) => d.importance), 0.0001);

  return (
    <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
        Sensitivity — top parameters driving the simulation
      </p>
      <div className="space-y-2.5">
        {drivers.map((d) => (
          <div key={d.parameter} className="flex items-center gap-3">
            <span className="w-56 shrink-0 truncate text-sm text-clinova-deep" title={d.parameter}>
              {d.parameter.replace(/_/g, " ")}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-clinova-deep"
                style={{ width: `${Math.max((d.importance / max) * 100, 4)}%` }}
              />
            </div>
            <span className="w-14 shrink-0 text-right font-mono text-xs text-neutral">
              {d.importance.toFixed(3)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
