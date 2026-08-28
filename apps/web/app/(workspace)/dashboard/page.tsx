import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { CountStatView } from "@/components/data/count-stat";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { PageHero } from "@/components/shell/page-hero";
import { api } from "@/lib/api";
import { getSelectedProject } from "@/lib/project";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const project = await getSelectedProject();

  if (!project) {
    return (
      <EmptyState
        title="No projects yet"
        description="Runs created in the Streamlit workspace appear here automatically."
        action={{ label: "Open Streamlit", href: "http://localhost:8501" }}
      />
    );
  }

  const dashboard = await api.getDashboard(project.project_id);

  if (dashboard.empty_reason) {
    return (
      <EmptyState
        title="No runs in this project yet"
        description={dashboard.empty_reason}
        action={{ label: "View all runs", href: "/runs" }}
      />
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-10">
      <PageHero
        eyebrow="Project Dashboard"
        title={dashboard.project_label}
        description={
          dashboard.basis_run && (
            <>
              {dashboard.basis_note}{" "}
              <Link href={`/runs/${dashboard.basis_run.run_id}`} className="text-clinova-deep underline">
                View run
              </Link>
            </>
          )
        }
      />

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Corpus at a glance</h2>
        <div className="grid grid-cols-4 gap-4">
          {dashboard.counts.map((c) => (
            <CountStatView key={c.key} stat={c} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Confidence</h2>
        <div className="grid grid-cols-5 gap-4">
          {dashboard.confidence.map((m) => (
            <ConfidenceStat key={m.key} measure={m} />
          ))}
        </div>
      </section>

      <section className="grid grid-cols-2 gap-8">
        <div>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
            Top research opportunities
          </h2>
          {dashboard.top_opportunities.length === 0 ? (
            <EmptyState
              title="No open opportunities yet"
              description="Gaps reach this list once the Gap Challenger stage assigns them an actionable status."
            />
          ) : (
            <ul className="space-y-2">
              {dashboard.top_opportunities.map((g) => (
                <li
                  key={g.gap_id ?? g.title}
                  className="group rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
                >
                  <Link
                    href={`/runs/${g.run_id}`}
                    className="flex items-start justify-between gap-2 font-medium text-clinova-deep hover:underline"
                  >
                    {g.title}
                    <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-clinova-cyan opacity-0 transition-opacity group-hover:opacity-100" />
                  </Link>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <StatusBadge chip={g.validation} size="sm" />
                    <StatusBadge chip={g.challenge} size="sm" />
                  </div>
                  {g.evidence_basis && <p className="mt-2 text-xs text-neutral">{g.evidence_basis}</p>}
                </li>
              ))}
            </ul>
          )}
          {dashboard.n_excluded_insufficient_evidence > 0 && (
            <p className="mt-3 text-xs text-neutral">
              {dashboard.n_excluded_insufficient_evidence} further candidate gap(s) could not be assessed —
              insufficient search coverage.
            </p>
          )}
        </div>

        <div>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Recent runs</h2>
          <ul className="space-y-2">
            {dashboard.recent_runs.map((r) => (
              <li
                key={r.run_id}
                className="group rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
              >
                <div className="flex items-center justify-between">
                  <Link href={`/runs/${r.run_id}`} className="font-medium text-clinova-deep hover:underline">
                    {r.name}
                  </Link>
                  <StatusBadge chip={r.status} size="sm" />
                </div>
                <p className="mt-1 font-mono text-xs text-neutral">
                  {r.run_id.slice(0, 8)} · {r.n_papers}p · {r.n_gaps}g · {r.n_proposals}pr
                </p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Research activity</h2>
        <ol className="space-y-3 border-l-2 border-clinova-light/30 pl-4">
          {dashboard.activity.map((a, i) => (
            <li key={`${a.kind}-${i}`} className="relative">
              <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-gradient-to-br from-clinova-cyan to-clinova-deep shadow-glow-sm" />
              <Link href={a.href} className="text-sm font-medium text-clinova-deep hover:underline">
                {a.title}
              </Link>
              <p className="text-xs text-neutral">
                {a.detail} · <span className="font-mono">{a.timestamp}</span>
              </p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
