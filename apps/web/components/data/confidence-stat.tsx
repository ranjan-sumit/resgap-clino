import { StatusBadge } from "@/components/data/status-badge";
import { StatRing } from "@/components/data/stat-ring";
import type { Measure } from "@/lib/api";

// 02-ux-specification.md §6: "Confidence values are always shown with
// their source... never a bare percentage with no explanation available
// on demand." The basis line is body copy here, not a hover-only
// tooltip -- it must be visible without interaction.
export function ConfidenceStat({ measure }: { measure: Measure }) {
  return (
    <div className="group relative overflow-hidden rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
      <div className="absolute inset-x-0 top-0 h-[3px] bg-accent-line opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">{measure.label}</div>
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
              ? "font-display text-clinova-deep text-3xl"
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
