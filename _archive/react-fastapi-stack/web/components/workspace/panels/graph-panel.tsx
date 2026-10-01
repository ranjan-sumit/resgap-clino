import { ConfidenceStat } from "@/components/data/confidence-stat";
import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { ForceGraph } from "@/components/graph/force-graph";
import { entityColor } from "@/components/graph/entity-colors";
import { api } from "@/lib/api";
import type { PanelProps } from "@/components/workspace/panel-props";
import type { GraphView } from "@/lib/api";

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

export async function GraphPanel({ projectId, runId }: PanelProps) {
  const graph = await api.graph(projectId, runId);
  const relationshipGroups = groupBySource(graph.relationships);
  const entityById = new Map(graph.entities.map((e) => [e.id, e]));

  return (
    <div className="space-y-8">
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
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Graph explorer
            </h2>
            <ForceGraph entities={graph.entities} relationships={graph.relationships} />
          </section>

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
              Entities, by type ({graph.entities.length})
            </h2>
            {/* Each type's chips are tinted with the EXACT color that type's
                dots use in the graph above (both read entityColor()), so the
                list and the diagram are visibly the same dataset rather than
                two unrelated views. High-importance entities are bolded --
                the one piece of emphasis that reflects real extracted data. */}
            <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <div className="space-y-4">
                {groupByType(graph.entities).map(([type, items]) => (
                  <div key={type}>
                    <p className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-neutral">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ background: entityColor(type) }}
                      />
                      {type} <span className="font-normal normal-case text-neutral/70">({items.length})</span>
                    </p>
                    <div className="flex flex-wrap gap-1.5 pl-3.5">
                      {items.map((e) => (
                        <span
                          key={e.id}
                          // max-w + truncate: the LLM extractor sometimes
                          // emits a whole finding sentence as a "concept"
                          // (e.g. "ADHD traits significantly predict ...
                          // (OR=1.04, p<0.001)"), which would otherwise
                          // render as a chip spanning the full row. Full
                          // text stays available on hover.
                          className={`max-w-md truncate rounded px-2 py-0.5 text-sm text-foreground ${
                            e.importance === "high" ? "font-semibold" : ""
                          }`}
                          style={{
                            background: `${entityColor(type)}14`,
                            boxShadow: `inset 0 0 0 1px ${entityColor(type)}33`,
                          }}
                          title={`${e.name}\n\n${type} · importance: ${e.importance}`}
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
            {/* source/target are entity IDs, not names -- rendering them raw
                showed slugs like "autism_spectrum_disorder_asd" instead of
                "Autism Spectrum Disorder (ASD)". Resolved through the entity
                map, with the id kept only as a fallback for a dangling edge. */}
            <ul className="divide-y divide-border/60 rounded-lg border border-border/60 bg-card shadow-card">
              {relationshipGroups.slice(0, 40).map(([source, edges]) => {
                const sourceEntity = entityById.get(source);
                return (
                  <li key={source} className="px-4 py-3 text-sm">
                    <p className="flex items-center gap-2 font-medium text-foreground">
                      {sourceEntity && (
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: entityColor(sourceEntity.type) }}
                        />
                      )}
                      {sourceEntity?.name ?? source}
                    </p>
                    <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1.5 pl-3.5">
                      {edges.map((e, i) => {
                        const targetEntity = entityById.get(e.target);
                        return (
                          <span
                            key={i}
                            className="inline-flex max-w-lg items-center gap-1.5 text-xs"
                            title={[targetEntity?.name ?? e.target, e.paper].filter(Boolean).join("\n\n")}
                          >
                            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-neutral">
                              {e.relation}
                            </span>
                            <span className="truncate text-foreground">
                              {targetEntity?.name ?? e.target}
                            </span>
                          </span>
                        );
                      })}
                    </div>
                  </li>
                );
              })}
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
