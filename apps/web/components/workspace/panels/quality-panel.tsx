import { ConfidenceStat } from "@/components/data/confidence-stat";
import { EmptyState } from "@/components/data/empty-state";
import { StatusBadge } from "@/components/data/status-badge";
import { FieldGrid } from "@/components/quality/field-grid";
import { api } from "@/lib/api";
import type { PanelProps } from "@/components/workspace/panel-props";

export async function QualityPanel({ projectId, runId }: PanelProps) {
  const quality = await api.quality(projectId, runId);

  return (
    <div className="space-y-8">
      {quality.empty_reason ? (
        <EmptyState title="No quality data yet" description={quality.empty_reason} />
      ) : (
        <>
          {quality.quality_gate && (
            <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">
                Corpus quality gate
              </p>
              <StatusBadge chip={quality.quality_gate} />
              {/* The reasons are also inside the chip's tooltip, but a gate
                  result is the one thing on this screen a reader must not
                  have to hover to learn. */}
              {quality.quality_gate_reasons.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {quality.quality_gate_reasons.map((r, i) => (
                    <li key={i} className="text-sm text-neutral">
                      — {r}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Extraction measures
            </h2>
            <div className="grid grid-cols-2 gap-4">
              {quality.measures.map((m) => (
                <ConfidenceStat key={m.key} measure={m} />
              ))}
            </div>
          </section>

          {quality.reference_funnel.length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
                Reference resolution funnel
              </h2>
              <div className="grid grid-cols-7 gap-3">
                {quality.reference_funnel.map((stage) => (
                  <div
                    key={stage.key}
                    className="rounded-lg border border-border/60 bg-card p-3 text-center shadow-card"
                  >
                    <p className="font-display text-3xl text-clinova-deep">{stage.count}</p>
                    <p className="mt-1 text-[10px] uppercase leading-tight tracking-wide text-neutral">
                      {stage.label}
                    </p>
                  </div>
                ))}
              </div>
              {/* Rendered as body copy, not a footnote: without it the row
                  above reads "114 detected, 0 parsed, 72 resolved", which
                  looks like a bug in this page rather than two counters
                  measuring different populations. */}
              {quality.funnel_note && (
                <p className="mt-3 rounded-md border border-border/60 bg-secondary/60 p-3 text-xs leading-relaxed text-slate-700">
                  {quality.funnel_note}
                </p>
              )}
            </section>
          )}

          {quality.trust_statuses.length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
                Reference trust (ADR-007)
              </h2>
              <ul className="divide-y divide-border/60 rounded-lg border border-border/60 bg-card shadow-card">
                {quality.trust_statuses.map((t) => (
                  <li key={t.status.code} className="flex items-start gap-4 px-4 py-3">
                    <div className="w-40 shrink-0">
                      <StatusBadge chip={t.status} size="sm" />
                    </div>
                    <p className="flex-1 text-xs leading-relaxed text-neutral">{t.status.reason}</p>
                    <p
                      className={
                        t.recorded
                          ? "w-24 shrink-0 text-right font-display text-2xl text-clinova-deep"
                          : "w-24 shrink-0 text-right text-xs italic text-neutral"
                      }
                    >
                      {t.recorded ? t.count : "Not recorded"}
                    </p>
                  </li>
                ))}
              </ul>
              <div className="mt-3 space-y-1">
                {quality.trust_note && <p className="text-xs text-neutral">{quality.trust_note}</p>}
                {quality.duplicates_removed != null && (
                  <p className="text-xs text-neutral">
                    {quality.duplicates_removed} duplicate reference
                    {quality.duplicates_removed === 1 ? " was" : "s were"} merged before resolution.
                  </p>
                )}
              </div>
            </section>
          )}

          {quality.per_paper_references.length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
                Reference extraction, per paper
              </h2>
              <ul className="space-y-2">
                {quality.per_paper_references.map((p) => (
                  <li
                    key={p.filename}
                    className="rounded-lg border border-border/60 bg-card p-4 shadow-card"
                  >
                    <p className="font-medium text-clinova-deep">{p.filename}</p>
                    <p className="mt-1.5 font-mono text-xs text-neutral">
                      {p.raw_entries} detected · {p.structured_entries} LLM-structured ·{" "}
                      {p.combined_entries} combined · {p.dois} with a DOI
                    </p>
                    {p.note && <p className="mt-2 text-xs leading-relaxed text-slate-700">{p.note}</p>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Field completeness, per paper
            </h2>
            {quality.per_paper_completeness.length > 0 ? (
              <div className="space-y-4">
                {quality.per_paper_completeness.map((p) => (
                  <FieldGrid key={p.filename} paper={p} />
                ))}
              </div>
            ) : (
              /* A full-height EmptyState here gave a one-sentence caveat as
                 much of the page as the four sections that carry real data.
                 The explanation still has to be visible -- it just should not
                 outweigh the findings above it. */
              <div className="rounded-lg border border-dashed border-border bg-card p-5 shadow-card">
                <p className="text-sm font-medium text-clinova-deep">Not recorded for this run</p>
                <p className="mt-1.5 max-w-3xl text-xs leading-relaxed text-neutral">
                  {quality.completeness_absent_reason ?? "No per-paper breakdown available."}
                </p>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
