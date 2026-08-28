import type { PaperCompleteness } from "@/lib/api";

// Three statuses, three distinct SHAPES plus their own words -- deliberately
// not the semantic palette. Two reasons: 02-ux-specification.md §3 confines
// those classes to status-badge.tsx/metric-delta.tsx, and "not extracted"
// is not a failure to colour red -- it means no extraction path exists
// anywhere in the pipeline for that field yet, which is a fact about the
// pipeline, not about the paper.
const STATUS_STYLE: Record<string, { dot: string; label: string }> = {
  present: { dot: "bg-clinova-deep", label: "Found" },
  empty: { dot: "border-2 border-clinova-blue bg-transparent", label: "Attempted, empty" },
  not_extracted: { dot: "border border-dashed border-neutral/50 bg-transparent", label: "No extraction path" },
};

export function FieldGrid({ paper }: { paper: PaperCompleteness }) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
      <div className="mb-1 flex items-baseline justify-between gap-4">
        <p className="font-medium text-clinova-deep">{paper.filename}</p>
        <p className="font-mono text-xs text-neutral">
          {paper.present_count}/{paper.total_fields} fields
        </p>
      </div>
      {/* Both numbers, both labelled. The raw score alone reads as a badly
          extracted paper; the achievable score alone hides how much of the
          checklist the pipeline still cannot reach at all. */}
      <p className="mb-4 text-xs leading-relaxed text-neutral">
        {(paper.completeness_score * 100).toFixed(0)}% of all {paper.total_fields} checklist fields ·{" "}
        <span className="font-medium text-slate-700">
          {(paper.achievable_completeness_score * 100).toFixed(0)}% of the{" "}
          {paper.achievable_field_count} the pipeline can extract today
        </span>{" "}
        — the quality gate judges the second figure.
      </p>

      <ul className="grid grid-cols-2 gap-x-8 gap-y-1.5">
        {paper.fields.map((f) => {
          const s = STATUS_STYLE[f.status] ?? STATUS_STYLE.not_extracted;
          return (
            <li key={f.field} className="flex items-baseline gap-2 text-sm">
              <span className={`h-2 w-2 shrink-0 translate-y-1 rounded-full ${s.dot}`} aria-hidden />
              <span className={f.status === "present" ? "text-slate-800" : "text-neutral"}>{f.label}</span>
              <span
                className="ml-auto shrink-0 text-right text-[11px] text-neutral/80"
                title={f.reason ?? f.source ?? undefined}
              >
                {s.label}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
