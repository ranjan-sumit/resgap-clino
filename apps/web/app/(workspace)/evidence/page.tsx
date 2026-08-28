import type { Metadata } from "next";
import { PageHero } from "@/components/shell/page-hero";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import { getSelectedProject } from "@/lib/project";
import { common } from "@/lib/copy";

export const metadata: Metadata = { title: "Evidence" };

export default async function EvidencePage() {
  const project = await getSelectedProject();
  if (!project) {
    return <EmptyState title={common.no_projects_title} description={common.no_projects_body} />;
  }

  const evidence = await api.evidence(project.project_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero eyebrow="Research" title="Evidence" description={evidence.basis_note} />

      <ConfidenceStat measure={evidence.confidence} />

      {Object.keys(evidence.by_type_counts).length > 0 && (
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">By type</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(evidence.by_type_counts).map(([type, count]) => (
              <span
                key={type}
                className="rounded-full border border-border/60 bg-card px-3 py-1 text-xs text-clinova-deep shadow-card"
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
                <p className="mt-2 text-sm text-slate-800">{e.text}</p>
                <p className="mt-2 font-mono text-xs text-neutral">
                  {e.paper_filename}
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
