import type { Metadata } from "next";
import Link from "next/link";
import { PageHero } from "@/components/shell/page-hero";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import { getSelectedProject } from "@/lib/project";
import { common } from "@/lib/copy";

export const metadata: Metadata = { title: "Research Gaps" };

export default async function GapsPage() {
  const project = await getSelectedProject();
  if (!project) {
    return <EmptyState title={common.no_projects_title} description={common.no_projects_body} />;
  }

  const dashboard = await api.getDashboard(project.project_id);
  if (!dashboard.basis_run) {
    return (
      <EmptyState
        title="No runs yet"
        description={dashboard.empty_reason ?? "No runs exist for this project yet."}
      />
    );
  }

  const run = await api.getRun(dashboard.basis_run.run_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero
        eyebrow="Intelligence"
        title="Research Gaps"
        description={`Reflects run "${run.name}" (${run.run_id.slice(0, 8)}) — the most recent run in this project.`}
      />

      {run.gaps.length === 0 ? (
        <EmptyState title="No gaps recorded" description="No research gaps were extracted for this run." />
      ) : (
        <ul className="space-y-3">
          {run.gaps.map((g, i) => (
            <li
              key={g.gap_id ?? i}
              className="rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
            >
              <p className="font-display text-lg text-clinova-deep">{g.title}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StatusBadge chip={g.validation} size="sm" />
                <StatusBadge chip={g.challenge} size="sm" />
                <span className="text-xs text-neutral">Confidence: {g.confidence.display}</span>
              </div>
              {g.evidence_basis && <p className="mt-2 text-sm text-neutral">{g.evidence_basis}</p>}
              {g.source && (
                <p className="mt-1 text-xs uppercase tracking-wide text-neutral">Source: {g.source}</p>
              )}

              {/* Cross-links: where this gap came from, and what it led to.
                  A supporting paper that isn't one of the uploaded PDFs has
                  no detail screen, so it renders as plain text rather than a
                  link that would 404. */}
              {(g.supporting_papers.length > 0 || g.proposals.length > 0) && (
                <div className="mt-4 grid grid-cols-2 gap-4 border-t border-border/60 pt-3">
                  {g.supporting_papers.length > 0 && (
                    <div>
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-neutral">
                        Derived from
                      </p>
                      <ul className="space-y-1 text-xs">
                        {g.supporting_papers.map((p, j) => (
                          <li key={j}>
                            {p.href ? (
                              <Link href={p.href} className="text-clinova-deep hover:underline">
                                {p.label}
                              </Link>
                            ) : (
                              <span className="text-slate-800">{p.label}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {g.proposals.length > 0 && (
                    <div>
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-neutral">
                        Addressed by
                      </p>
                      <ul className="space-y-1 text-xs">
                        {g.proposals.map((p, j) => (
                          <li key={j}>
                            {p.href ? (
                              <Link href={p.href} className="text-clinova-deep hover:underline">
                                {p.label}
                              </Link>
                            ) : (
                              <span className="text-slate-800">{p.label}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <Link href={`/runs/${run.run_id}`} className="inline-block text-sm text-clinova-deep hover:underline">
        View full run detail &rarr;
      </Link>
    </div>
  );
}
