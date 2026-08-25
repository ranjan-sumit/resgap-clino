import { PageHero } from "@/components/shell/page-hero";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import type { GraphView } from "@/lib/api";

// A muted dot per type -- enough to scan by type without turning the
// entity list into a wall of rainbow badges (the "tag soup" problem the
// original full-color-pill version had).
const TYPE_DOT: Record<string, string> = {
  concept: "bg-clinova-cyan", method: "bg-clinova-light", dataset: "bg-semantic-success",
  metric: "bg-semantic-warning", problem: "bg-semantic-critical", domain: "bg-clinova-blue",
  model: "bg-clinova-deep",
};

function groupByType(entities: GraphView["entities"]) {
  const groups = new Map<string, GraphView["entities"]>();
  for (const e of entities) {
    const list = groups.get(e.type) ?? [];
    list.push(e);
    groups.set(e.type, list);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
}

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
                    {c.gap_signal && <p className="mt-2 text-xs italic text-neutral">{c.gap_signal}</p>}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Entities ({graph.entities.length})
            </h2>
            <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <div className="space-y-4">
                {groupByType(graph.entities).map(([type, items]) => (
                  <div key={type}>
                    <p className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-neutral">
                      <span className={`h-1.5 w-1.5 rounded-full ${TYPE_DOT[type] ?? "bg-neutral"}`} />
                      {type} <span className="font-normal normal-case text-neutral/70">({items.length})</span>
                    </p>
                    <div className="flex flex-wrap gap-x-3 gap-y-1.5 pl-3.5">
                      {items.map((e) => (
                        <span
                          key={e.id}
                          className="text-sm text-slate-800"
                          title={`importance: ${e.importance}`}
                        >
                          {e.name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Relationships ({graph.relationships.length})
            </h2>
            <ul className="divide-y divide-border/60 rounded-lg border border-border/60 bg-card shadow-card">
              {graph.relationships.slice(0, 60).map((r, i) => (
                <li key={i} className="px-4 py-2.5 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-800">{r.source}</span>
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-neutral">
                      {r.relation}
                    </span>
                    <span className="text-slate-800">{r.target}</span>
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
