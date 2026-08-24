import { PageHero } from "@/components/shell/page-hero";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

const ENTITY_TYPE_STYLE: Record<string, string> = {
  concept: "bg-clinova-cyan/10 text-clinova-deep",
  method: "bg-clinova-light/15 text-clinova-deep",
  dataset: "bg-semantic-success/10 text-semantic-success",
  metric: "bg-semantic-warning/10 text-semantic-warning",
  problem: "bg-semantic-critical/10 text-semantic-critical",
  domain: "bg-clinova-blue/10 text-clinova-deep",
  model: "bg-clinova-deep/10 text-clinova-deep",
};

export default async function KnowledgeGraphPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const graph = await api.graph(projects[0].project_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero eyebrow="Research" title="Knowledge Graph" description={graph.basis_note} />

      <div className="grid grid-cols-5 gap-4">
        {graph.counts.map((c) => (
          <CountStatView key={c.key} stat={c} />
        ))}
      </div>

      <ConfidenceStat measure={graph.confidence} />

      {graph.empty_reason ? (
        <EmptyState title="No graph yet" description={graph.empty_reason} />
      ) : (
        <>
          {graph.communities.length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
                Thematic communities ({graph.communities.length})
              </h2>
              <div className="grid grid-cols-2 gap-4">
                {graph.communities.map((c) => (
                  <div key={c.id} className="rounded-lg border border-border/60 bg-card p-4 shadow-card">
                    <p className="font-medium text-clinova-deep">{c.theme}</p>
                    <p className="mt-1 text-sm text-neutral">{c.summary}</p>
                    {c.gap_signal && <p className="mt-2 text-xs italic text-clinova-blue">{c.gap_signal}</p>}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Entities ({graph.entities.length})
            </h2>
            <div className="flex flex-wrap gap-2">
              {graph.entities.map((e) => (
                <span
                  key={e.id}
                  className={`rounded-full px-3 py-1 text-xs font-medium shadow-sm ${ENTITY_TYPE_STYLE[e.type] ?? "bg-muted text-neutral"}`}
                  title={`${e.type} · importance: ${e.importance}`}
                >
                  {e.name}
                </span>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Relationships ({graph.relationships.length})
            </h2>
            <ul className="space-y-1.5">
              {graph.relationships.slice(0, 60).map((r, i) => (
                <li
                  key={i}
                  className="rounded-lg border border-border/60 bg-card px-4 py-2.5 text-sm shadow-card"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-clinova-deep">{r.source}</span>
                    <span className="shrink-0 rounded-full bg-clinova-cyan/10 px-2 py-0.5 text-xs text-clinova-blue">
                      {r.relation}
                    </span>
                    <span className="font-medium text-clinova-deep">{r.target}</span>
                  </div>
                  {r.paper && <p className="mt-1 truncate text-xs text-neutral" title={r.paper}>{r.paper}</p>}
                </li>
              ))}
            </ul>
            {graph.relationships.length > 60 && (
              <p className="mt-2 text-xs text-neutral">Showing the first 60 of {graph.relationships.length}.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
