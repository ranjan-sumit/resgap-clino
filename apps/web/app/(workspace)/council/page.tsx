import { PageHero } from "@/components/shell/page-hero";
import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

function ListSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">{title}</p>
      <ul className="list-disc space-y-1 pl-4 text-sm text-clinova-deep">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export default async function ResearchCouncilPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const council = await api.council(projects[0].project_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero eyebrow="Intelligence" title="Research Council" description={council.basis_note} />

      {council.empty_reason ? (
        <EmptyState title="No council run yet" description={council.empty_reason} />
      ) : (
        <>
          <div className="grid grid-cols-5 gap-4">
            {council.params_summary.map((c) => (
              <CountStatView key={c.key} stat={c} />
            ))}
          </div>

          {council.novel_finding && (
            <section className="relative overflow-hidden rounded-xl bg-hero-gradient p-6 text-white shadow-raised">
              <div className="pointer-events-none absolute inset-0 bg-brand-glow opacity-60" aria-hidden />
              <div className="relative">
                <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-clinova-cyan">
                  Novel Finding · {council.novel_finding.confidence} confidence
                </p>
                <h2 className="font-display text-2xl">{council.novel_finding.title}</h2>
                <p className="mt-3 max-w-3xl text-sm leading-relaxed text-white/85">{council.novel_finding.claim}</p>
                <p className="mt-3 max-w-3xl text-xs text-white/60">{council.novel_finding.what_makes_it_new}</p>
                <div className="mt-5 grid grid-cols-2 gap-4 text-xs text-white/75">
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-clinova-cyan">Mechanism</p>
                    <p>{council.novel_finding.mechanism}</p>
                  </div>
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-clinova-cyan">
                      Suggested validation
                    </p>
                    <p>{council.novel_finding.validation_study}</p>
                  </div>
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-clinova-cyan">
                      Clinical opportunity
                    </p>
                    <p>{council.novel_finding.clinical_opportunity}</p>
                  </div>
                  <div>
                    <p className="mb-1 font-semibold uppercase tracking-wide text-clinova-cyan">
                      Commercial opportunity
                    </p>
                    <p>{council.novel_finding.commercial_opportunity}</p>
                  </div>
                </div>
                {council.novel_finding.evidence_chain.length > 0 && (
                  <div className="mt-5 border-t border-white/15 pt-4">
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-clinova-cyan">
                      Evidence chain
                    </p>
                    <ul className="list-disc space-y-1 pl-4 text-xs text-white/75">
                      {council.novel_finding.evidence_chain.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </section>
          )}

          {council.model_selection && (
            <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">
                Model selection · {council.model_selection.confidence} confidence
              </p>
              <p className="font-display text-xl text-clinova-deep">{council.model_selection.selected_model}</p>
              <p className="mt-2 text-sm text-neutral">{council.model_selection.rationale}</p>
            </section>
          )}

          {Object.keys(council.sim_headline_numbers).length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
                Simulation headline numbers
              </h2>
              <div className="grid grid-cols-4 gap-3">
                {Object.entries(council.sim_headline_numbers).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-border/60 bg-card p-4 shadow-card">
                    <p className="stat-gradient-text font-display text-2xl">
                      {typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v)}
                    </p>
                    <p className="mt-1 text-[10px] uppercase tracking-wide text-neutral">{k.replace(/_/g, " ")}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

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
        </>
      )}
    </div>
  );
}
