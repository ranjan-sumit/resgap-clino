import type { Metadata } from "next";
import Link from "next/link";
import { PageHero } from "@/components/shell/page-hero";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

export const metadata: Metadata = { title: "Research Gaps" };

export default async function GapsPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const dashboard = await api.getDashboard(projects[0].project_id);
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
