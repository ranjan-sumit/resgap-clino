import type { Metadata } from "next";
import Link from "next/link";
import { PageHero } from "@/components/shell/page-hero";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

export const metadata: Metadata = { title: "Corpus" };

export default async function CorpusPage() {
  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const corpus = await api.corpus(projects[0].project_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero eyebrow="Research" title="Corpus" description={corpus.basis_note} />

      {corpus.empty_reason ? (
        <EmptyState title="No corpus yet" description={corpus.empty_reason} />
      ) : (
        <>
          <section className="grid grid-cols-3 gap-4">
            <ConfidenceStat measure={corpus.corpus_confidence} />
            <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">DOI resolution</p>
              <p className="font-display text-clinova-deep text-3xl">
                {corpus.doi_resolution_rate != null ? `${(corpus.doi_resolution_rate * 100).toFixed(0)}%` : "Not recorded"}
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">Abstract availability</p>
              <p className="font-display text-clinova-deep text-3xl">
                {corpus.abstract_availability != null ? `${(corpus.abstract_availability * 100).toFixed(0)}%` : "Not recorded"}
              </p>
            </div>
          </section>

          {corpus.quality_gate && (
            <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">Quality gate</p>
              <StatusBadge chip={corpus.quality_gate} />
            </section>
          )}

          {corpus.reference_funnel.length > 0 && (
            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Reference funnel</h2>
              <div className="grid grid-cols-7 gap-3">
                {corpus.reference_funnel.map((stage) => (
                  <div key={stage.key} className="rounded-lg border border-border/60 bg-card p-3 text-center shadow-card">
                    <p className="font-display text-clinova-deep text-2xl">{stage.count}</p>
                    <p className="mt-1 text-[10px] uppercase tracking-wide text-neutral">{stage.label}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Papers ({corpus.papers.length})
            </h2>
            <ul className="space-y-2">
              {corpus.papers.map((p, i) => (
                <li key={i}>
                  <Link
                    href={`/corpus/papers/${encodeURIComponent(p.filename)}`}
                    className="block rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
                  >
                    <p className="font-medium text-clinova-deep">{p.title ?? p.filename}</p>
                    <p className="mt-1 font-mono text-xs text-neutral">
                      {p.filename} · {p.char_count.toLocaleString()} chars
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
