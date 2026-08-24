import { StatusBadge } from "@/components/data/status-badge";
import type { Measure } from "@/lib/api";

// 02-ux-specification.md §6: "Confidence values are always shown with
// their source... never a bare percentage with no explanation available
// on demand." The basis line is body copy here, not a hover-only
// tooltip -- it must be visible without interaction.
export function ConfidenceStat({ measure }: { measure: Measure }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5 shadow-card">
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">{measure.label}</div>
      <div
        className={
          measure.recorded
            ? "font-display text-4xl text-clinova-deep"
            : "font-sans text-xl italic text-neutral"
        }
      >
        {measure.display}
      </div>
      {measure.status && (
        <div className="mt-2">
          <StatusBadge chip={measure.status} size="sm" />
        </div>
      )}
      <p className="mt-2 text-xs leading-relaxed text-neutral">{measure.basis}</p>
    </div>
  );
}
