import { PageHero } from "@/components/shell/page-hero";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

const RISK_TONE: Record<string, string> = {
  low: "text-semantic-success",
  medium: "text-semantic-warning",
  high: "text-semantic-critical",
};

export default async function ProposalsPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const dashboard = await api.getDashboard(projects[0].project_id);
  if (!dashboard.basis_run) {
    return <EmptyState title="No runs yet" description={dashboard.empty_reason ?? "No runs exist for this project yet."} />;
  }

  const run = await api.getRun(dashboard.basis_run.run_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero
        eyebrow="Intelligence"
        title="Proposals"
        description={`Reflects run "${run.name}" (${run.run_id.slice(0, 8)}) — the most recent run in this project.`}
      />

      {run.proposals.length === 0 ? (
        <EmptyState title="No proposals recorded" description="No research proposals were generated for this run." />
      ) : (
        <div className="space-y-4">
          {run.proposals.map((p, i) => (
            <div key={i} className="rounded-xl border border-border/60 bg-card p-6 shadow-card">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="font-display text-xl text-clinova-deep">{p.title}</p>
                <div className="flex shrink-0 items-center gap-2 text-xs">
                  {p.effort_estimate && (
                    <span className="rounded-full bg-clinova-light/10 px-2.5 py-1 text-clinova-deep">
                      {p.effort_estimate}
                    </span>
                  )}
                  {p.risk && (
                    <span className={`font-medium ${RISK_TONE[p.risk] ?? "text-neutral"}`}>{p.risk} risk</span>
                  )}
                </div>
              </div>

              {p.problem_statement && <p className="mt-3 text-sm text-neutral">{p.problem_statement}</p>}

              <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
                {p.methodology && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">Methodology</p>
                    <p className="text-clinova-deep">{p.methodology}</p>
                  </div>
                )}
                {p.novelty && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">Novelty</p>
                    <p className="text-clinova-deep">{p.novelty}</p>
                  </div>
                )}
                {p.expected_contribution && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">
                      Expected contribution
                    </p>
                    <p className="text-clinova-deep">{p.expected_contribution}</p>
                  </div>
                )}
                {p.builds_on.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">Builds on</p>
                    <p className="text-clinova-deep">{p.builds_on.join(", ")}</p>
                  </div>
                )}
              </div>

              {p.suggested_experiments.length > 0 && (
                <div className="mt-4 border-t border-border/60 pt-4">
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral">
                    Suggested experiments
                  </p>
                  <ul className="list-disc space-y-1 pl-4 text-sm text-clinova-deep">
                    {p.suggested_experiments.map((e, ei) => (
                      <li key={ei}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}

              <p className="mt-4 text-xs text-neutral">
                Addresses gap:{" "}
                {p.addresses_gap_id ? (
                  <span className="font-mono text-clinova-deep">{p.addresses_gap_id.slice(0, 8)}</span>
                ) : (
                  <span className="italic">unresolved ({p.addresses_gap_id_resolution ?? "no match"})</span>
                )}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
