import { StatusBadge } from "@/components/data/status-badge";
import { StatRing } from "@/components/data/stat-ring";
import { statIcon } from "@/components/data/stat-icons";
import type { Measure } from "@/lib/api";

// 02-ux-specification.md §6: "Confidence values are always shown with
// their source... never a bare percentage with no explanation available
// on demand." The basis line is body copy here, not a hover-only
// tooltip -- it must be visible without interaction.
export function ConfidenceStat({ measure }: { measure: Measure }) {
  const Icon = statIcon(measure.key);
  return (
    <div className="group relative overflow-hidden rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all duration-200 hover:-translate-y-px hover:shadow-card-hover">
      <div className="absolute inset-x-0 top-0 h-[3px] bg-accent-line opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
      <div className="mb-2.5 flex items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-clinova-blue/10 text-clinova-blue">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral">{measure.label}</div>
      </div>
      <div className="flex items-center gap-4">
        {measure.recorded && measure.value != null ? (
          <StatRing value={measure.value} />
        ) : (
          measure.recorded === false && (
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 border-dashed border-border text-[10px] font-medium uppercase text-neutral/50">
              N/A
            </div>
          )
        )}
        <div
          className={
            measure.recorded
              ? "text-[28px] font-semibold tracking-tight tabular-nums text-clinova-deep"
              : "font-sans text-lg italic text-neutral"
          }
        >
          {measure.display}
        </div>
      </div>
      {measure.status && (
        <div className="mt-3">
          <StatusBadge chip={measure.status} size="sm" />
        </div>
      )}
      <p className="mt-2 text-xs leading-relaxed text-neutral">{measure.basis}</p>
    </div>
  );
}
