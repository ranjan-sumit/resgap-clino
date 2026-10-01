import Link from "next/link";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import { common } from "@/lib/copy";
import type { PanelProps } from "@/components/workspace/panel-props";

export async function GapsPanel({ projectId, runId }: PanelProps) {
  // runId is already resolved by the workspace, so calling getDashboard here
  // just to read basis_run.run_id back out cost a second full dashboard
  // build -- ~14.7s of recent_runs/delta work this panel never renders,
  // which made this the slowest tab in the workspace by 4x.
  if (!runId) {
    return <EmptyState title={common.no_runs_title} description={common.no_runs_body} />;
  }

  const run = await api.getRun(runId);

  if (run.gaps.length === 0) {
    return <EmptyState title={common.no_gaps_title} description={common.no_gaps_body} />;
  }

  return (
    <div className="space-y-8">
      <ul className="space-y-3">
        {run.gaps.map((g, i) => (
          <li
            key={g.gap_id ?? i}
            className="rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
          >
            <p className="text-lg font-semibold tracking-tight text-clinova-deep">{g.title}</p>
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
                            <span className="text-foreground">{p.label}</span>
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
                            <span className="text-foreground">{p.label}</span>
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

      <Link href={`/runs/${run.run_id}`} className="inline-block text-sm text-clinova-deep hover:underline">
        View full run detail &rarr;
      </Link>
    </div>
  );
}
