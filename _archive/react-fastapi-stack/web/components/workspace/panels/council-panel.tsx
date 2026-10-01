import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import Link from "next/link";
import { hasModelling } from "@/components/council/modelling-panel";
import { RunComputationalLab } from "@/components/council/run-computational-lab";
import { api } from "@/lib/api";
import type { PanelProps } from "@/components/workspace/panel-props";

function ListSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">{title}</p>
      <ul className="list-disc space-y-1 pl-4 text-sm text-foreground">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export async function CouncilPanel({ projectId, runId }: PanelProps) {
  const council = await api.council(projectId, runId);
  const modellingAvailable = hasModelling(council);

  return (
    <div className="space-y-8">
      {council.empty_reason ? (
        runId ? (
          <div className="flex justify-center py-4">
            <RunComputationalLab runId={runId} tab="council" />
          </div>
        ) : (
          <EmptyState title="No council run yet" description={council.empty_reason} />
        )
      ) : (
        <>
          <div className="grid grid-cols-5 gap-4">
            {council.params_summary.map((c) => (
              <CountStatView key={c.key} stat={c} />
            ))}
          </div>
          {council.n_excluded_low_confidence > 0 && (
            <p className="text-xs text-neutral">
              {council.n_excluded_low_confidence} parameter(s) excluded from simulation — confidence too low.
            </p>
          )}

          {council.novel_finding && (
            <section className="rounded-xl border border-border/60 bg-card p-6 shadow-card">
              <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-clinova-deep">
                Novel Finding · {council.novel_finding.confidence} confidence
              </p>
              <h2 className="text-2xl font-semibold tracking-tight text-clinova-deep">{council.novel_finding.title}</h2>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-foreground">
                {council.novel_finding.claim}
              </p>
              <p className="mt-3 max-w-3xl text-xs text-neutral">{council.novel_finding.what_makes_it_new}</p>
              <div className="mt-5 grid grid-cols-2 gap-4 border-t border-border/60 pt-4 text-xs text-neutral">
                <div>
                  <p className="mb-1 font-semibold uppercase tracking-wide text-neutral">Mechanism</p>
                  <p>{council.novel_finding.mechanism}</p>
                </div>
                <div>
                  <p className="mb-1 font-semibold uppercase tracking-wide text-neutral">Suggested validation</p>
                  <p>{council.novel_finding.validation_study}</p>
                </div>
                <div>
                  <p className="mb-1 font-semibold uppercase tracking-wide text-neutral">Clinical opportunity</p>
                  <p>{council.novel_finding.clinical_opportunity}</p>
                </div>
                <div>
                  <p className="mb-1 font-semibold uppercase tracking-wide text-neutral">Commercial opportunity</p>
                  <p>{council.novel_finding.commercial_opportunity}</p>
                </div>
              </div>
              {council.novel_finding.evidence_chain.length > 0 && (
                <div className="mt-4 border-t border-border/60 pt-4">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral">Evidence chain</p>
                  <ul className="list-disc space-y-1 pl-4 text-xs text-neutral">
                    {council.novel_finding.evidence_chain.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {/* Slice 15: the inner "Computational modelling" tab is gone.
              Modelling is a workspace tab in its own right now, so keeping it
              here too put two tabs with the same label on one screen -- the
              exact confusion the top-level tab was added to fix. This panel
              is the findings and debate; modelling is one tab across. */}
          {modellingAvailable && (
            <Link
              href="/workspace?tab=modelling"
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm text-clinova-deep hover:bg-secondary"
            >
              Computational modelling results &rarr;
            </Link>
          )}

          <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <ListSection title="Clinical insights" items={council.clinical_insights} />
                <ListSection title="Research insights" items={council.research_insights} />
                <ListSection title="Key uncertainties" items={council.key_uncertainties} />
                <ListSection title="Actionable next steps" items={council.actionable_next_steps} />
              </div>
              <ListSection title="Limitations" items={council.limitations} />

              {council.insight_agents.length > 0 && (
                <section>
                  <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Council debate</h2>
                  <div className="space-y-3">
                    {council.insight_agents.map((a, i) => (
                      <div key={i} className="rounded-lg border border-border/60 bg-card p-4 shadow-card">
                        <p className="text-sm font-medium text-clinova-deep">
                          {a.agent} <span className="font-normal text-neutral">· {a.role}</span>
                        </p>
                        <p className="mt-1 font-mono text-[10px] text-neutral">{a.model}</p>
                        <p className="mt-2 whitespace-pre-line text-sm text-neutral">{a.response}</p>
                      </div>
                    ))}
                  </div>
                </section>
              )}
          </div>
        </>
      )}
    </div>
  );
}
