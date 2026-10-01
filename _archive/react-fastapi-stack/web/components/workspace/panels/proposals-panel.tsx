import Link from "next/link";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import { common } from "@/lib/copy";
import type { PanelProps } from "@/components/workspace/panel-props";

const RISK_TONE: Record<string, string> = {
  low: "text-semantic-success",
  medium: "text-semantic-warning",
  high: "text-semantic-critical",
};

export async function ProposalsPanel({ projectId, runId }: PanelProps) {
  // runId is already resolved by the workspace, so calling getDashboard here
  // just to read basis_run.run_id back out cost a second full dashboard
  // build -- ~14.7s of recent_runs/delta work this panel never renders,
  // which made this the slowest tab in the workspace by 4x.
  if (!runId) {
    return <EmptyState title={common.no_runs_title} description={common.no_runs_body} />;
  }

  const run = await api.getRun(runId);

  if (run.proposals.length === 0) {
    return (
      <EmptyState
        title="No proposals recorded"
        description="No research proposals were generated for this run."
      />
    );
  }

  return (
    <div className="space-y-4">
      {run.proposals.map((p, i) => (
        <div key={i} className="rounded-xl border border-border/60 bg-card p-6 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="text-xl font-semibold tracking-tight text-clinova-deep">{p.title}</p>
            <div className="flex shrink-0 items-center gap-2 text-xs">
              {p.effort_estimate && (
                <span className="rounded-full border border-border/60 bg-secondary px-2 py-0.5 text-[11px] font-medium text-clinova-deep">
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
                <p className="text-foreground">{p.methodology}</p>
              </div>
            )}
            {p.novelty && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">Novelty</p>
                <p className="text-foreground">{p.novelty}</p>
              </div>
            )}
            {p.expected_contribution && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">
                  Expected contribution
                </p>
                <p className="text-foreground">{p.expected_contribution}</p>
              </div>
            )}
            {p.builds_on.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">Builds on</p>
                <p className="text-foreground">{p.builds_on.join(", ")}</p>
              </div>
            )}
          </div>

          {p.suggested_experiments.length > 0 && (
            <div className="mt-4 border-t border-border/60 pt-4">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral">
                Suggested experiments
              </p>
              <ul className="list-disc space-y-1 pl-4 text-sm text-foreground">
                {p.suggested_experiments.map((e, ei) => (
                  <li key={ei}>{e}</li>
                ))}
              </ul>
            </div>
          )}

          {/* The pipeline records the addressed gap by title, not id, so
              the readable title is the useful link; the id line stays for
              provenance. A gap named but not present in this run is shown
              as text, never a link that would 404. */}
          <p className="mt-4 text-xs text-neutral">
            Addresses gap:{" "}
            {p.addresses_gap ? (
              p.addresses_gap.href ? (
                <Link href={p.addresses_gap.href} className="text-clinova-deep hover:underline">
                  {p.addresses_gap.label}
                </Link>
              ) : (
                <span className="text-foreground">{p.addresses_gap.label}</span>
              )
            ) : p.addresses_gap_id ? (
              <span className="font-mono text-clinova-deep">{p.addresses_gap_id.slice(0, 8)}</span>
            ) : (
              <span className="italic">unresolved ({p.addresses_gap_id_resolution ?? "no match"})</span>
            )}
          </p>
        </div>
      ))}
    </div>
  );
}
