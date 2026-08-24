import { PageHero } from "@/components/shell/page-hero";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

export default async function GapChallengerPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const view = await api.challenger(projects[0].project_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero eyebrow="Intelligence" title="Gap Challenger" description={view.basis_note} />

      {view.empty_reason ? (
        <EmptyState title="No gaps yet" description={view.empty_reason} />
      ) : (
        <ul className="space-y-4">
          {view.gaps.map((g, i) => (
            <li key={g.gap_id ?? i} className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="font-display text-lg text-clinova-deep">{g.title}</p>
                <StatusBadge chip={g.status} />
              </div>
              {g.reason && !g.funnel && <p className="mt-2 text-sm text-neutral">{g.reason}</p>}

              {g.funnel && (
                <div className="mt-4 space-y-4 border-t border-border/60 pt-4">
                  <div className="grid grid-cols-5 gap-3 text-center">
                    {[
                      ["Candidates", g.funnel.candidate_count],
                      ["After dedup", g.funnel.post_dedup_count],
                      ["After filter", g.funnel.post_metadata_filter_count],
                      ["After rerank", g.funnel.post_rerank_count],
                      ["Relevant", g.funnel.relevant_count],
                    ].map(([label, value]) => (
                      <div key={label as string} className="rounded-md bg-surface p-2">
                        <p className="font-display text-xl text-clinova-deep">{value}</p>
                        <p className="text-[10px] uppercase tracking-wide text-neutral">{label}</p>
                      </div>
                    ))}
                  </div>

                  <div className="flex flex-wrap items-center gap-3 text-xs text-neutral">
                    <span>
                      Coverage score:{" "}
                      <span className="font-mono text-clinova-deep">
                        {g.funnel.search_coverage_score != null
                          ? `${(g.funnel.search_coverage_score * 100).toFixed(0)}%`
                          : "Not recorded"}
                      </span>
                    </span>
                    {Object.entries(g.funnel.provider_success).map(([provider, ok]) => (
                      <span key={provider} className={ok ? "text-semantic-success" : "text-semantic-critical"}>
                        {ok ? "✓" : "✗"} {provider}
                      </span>
                    ))}
                  </div>

                  {g.funnel.query_families.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {g.funnel.query_families.map((q, qi) => (
                        <span key={qi} className="rounded-full bg-clinova-light/10 px-2 py-0.5 text-xs text-clinova-deep">
                          {q}
                        </span>
                      ))}
                    </div>
                  )}

                  {g.funnel.judged_candidates.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-neutral">
                        Judged candidates
                      </p>
                      {g.funnel.judged_candidates.map((c, ci) => (
                        <div key={ci} className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-clinova-deep">{c.title}</span>
                          <span className="flex shrink-0 items-center gap-2 text-xs text-neutral">
                            {c.relevant ? "Relevant" : "Not relevant"}
                            {c.contradicts_gap && <span className="text-semantic-warning">Contradicts</span>}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
