import type { Metadata } from "next";
import { PageHero } from "@/components/shell/page-hero";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import type { GraphView } from "@/lib/api";

export const metadata: Metadata = { title: "Knowledge Graph" };

// A muted dot per type -- enough to scan by type without turning the
// entity list into a wall of rainbow badges (the "tag soup" problem the
// original full-color-pill version had).
const TYPE_DOT: Record<string, string> = {
  concept: "bg-clinova-cyan", method: "bg-clinova-light", dataset: "bg-semantic-success",
  metric: "bg-semantic-warning", problem: "bg-semantic-critical", domain: "bg-clinova-blue",
  model: "bg-clinova-deep",
};

const COUNT_HINTS: Record<string, string> = {
  communities: "Thematic clusters of related entities, identified by an LLM pass over the graph. Often 0 for a fallback-built graph (no LLM entity extraction ran for this run).",
  orphans: "Entities with few or no relationships connecting them to the rest of the graph -- expected to be high on a fallback-built graph, which mostly has paper-to-concept \"mentions\" edges rather than concept-to-concept relationships.",
  bridges: "Cases where one paper's stated limitation could potentially be addressed by another paper's proposed solution -- a real cross-paper research-gap signal, not a graph-structure defect.",
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

function groupBySource(relationships: GraphView["relationships"]) {
  const groups = new Map<string, GraphView["relationships"]>();
  for (const r of relationships) {
    const list = groups.get(r.source) ?? [];
    list.push(r);
    groups.set(r.source, list);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
}

export default async function KnowledgeGraphPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const graph = await api.graph(projects[0].project_id);
  const relationshipGroups = groupBySource(graph.relationships);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero eyebrow="Research" title="Knowledge Graph" description={graph.basis_note} />

      <div className="grid grid-cols-5 gap-4">
        {graph.counts.map((c) => (
          <CountStatView key={c.key} stat={c} hint={COUNT_HINTS[c.key]} />
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
            {/* Grouped by source -- a fallback-built graph (no LLM entity
                extraction) is mostly "paper mentions concept" edges, so the
                same source repeats for dozens of rows; showing it once per
                group instead of once per edge is what makes this scannable. */}
            <ul className="divide-y divide-border/60 rounded-lg border border-border/60 bg-card shadow-card">
              {relationshipGroups.slice(0, 40).map(([source, edges]) => (
                <li key={source} className="px-4 py-3 text-sm">
                  <p className="font-medium text-slate-800">{source}</p>
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1.5 pl-3">
                    {edges.map((e, i) => (
                      <span
                        key={i}
                        className="inline-flex items-center gap-1.5 text-xs"
                        title={e.paper ?? undefined}
                      >
                        <span className="rounded bg-muted px-1.5 py-0.5 text-neutral">{e.relation}</span>
                        <span className="text-slate-800">{e.target}</span>
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
            {relationshipGroups.length > 40 && (
              <p className="mt-2 text-xs text-neutral">
                Showing the first 40 of {relationshipGroups.length} source entities.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
