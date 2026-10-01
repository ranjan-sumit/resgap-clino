import Link from "next/link";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import type { PanelProps } from "@/components/workspace/panel-props";

export async function EvidencePanel({ projectId, runId }: PanelProps) {
  const evidence = await api.evidence(projectId, runId);

  return (
    <div className="space-y-8">
      <ConfidenceStat measure={evidence.confidence} />

      {Object.keys(evidence.by_type_counts).length > 0 && (
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">By type</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(evidence.by_type_counts).map(([type, count]) => (
              <span
                key={type}
                className="rounded-full border border-border/60 bg-secondary px-2 py-0.5 text-[11px] font-medium text-clinova-deep"
              >
                {type} <span className="font-mono text-neutral">· {count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {evidence.empty_reason ? (
        <EmptyState title="No evidence yet" description={evidence.empty_reason} />
      ) : (
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
            Evidence objects ({evidence.items.length})
          </h2>
          <ul className="space-y-2">
            {evidence.items.map((e) => (
              <li
                key={e.evidence_id}
                className="rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="rounded-md bg-clinova-light/10 px-2 py-0.5 text-xs font-medium text-clinova-deep">
                    {e.evidence_type}
                  </span>
                  <span className="text-xs font-medium text-neutral">{e.confidence} confidence</span>
                </div>
                <p className="mt-2 text-sm text-foreground">{e.text}</p>
                <p className="mt-2 font-mono text-xs text-neutral">
                  {/* paper_filename is exactly the Paper Detail route param,
                      so evidence links straight to the paper it came from. */}
                  <Link
                    href={`/corpus/papers/${encodeURIComponent(e.paper_filename)}${runId ? `?run=${encodeURIComponent(runId)}` : ""}`}
                    className="text-clinova-deep hover:underline"
                  >
                    {e.paper_filename}
                  </Link>
                  {e.page != null ? ` · p.${e.page}` : ""}
                  {e.section ? ` · ${e.section}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
