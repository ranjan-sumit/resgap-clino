import Link from "next/link";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";
import type { PanelProps } from "@/components/workspace/panel-props";

export async function CorpusPanel({ projectId, runId }: PanelProps) {
  const corpus = await api.corpus(projectId, runId);

  if (corpus.empty_reason) {
    return <EmptyState title="No corpus yet" description={corpus.empty_reason} />;
  }

  return (
    <div className="space-y-8">
      <section className="grid grid-cols-3 gap-4">
        <ConfidenceStat measure={corpus.corpus_confidence} />
        <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">DOI resolution</p>
          <p className="text-3xl font-semibold tracking-tight text-clinova-deep">
            {corpus.doi_resolution_rate != null
              ? `${(corpus.doi_resolution_rate * 100).toFixed(0)}%`
              : "Not recorded"}
          </p>
        </div>
        <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral">Abstract availability</p>
          <p className="text-3xl font-semibold tracking-tight text-clinova-deep">
            {corpus.abstract_availability != null
              ? `${(corpus.abstract_availability * 100).toFixed(0)}%`
              : "Not recorded"}
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
              <div
                key={stage.key}
                className="rounded-lg border border-border/60 bg-card p-3 text-center shadow-card"
              >
                <p className="text-2xl font-semibold tracking-tight text-clinova-deep">{stage.count}</p>
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
                href={`/corpus/papers/${encodeURIComponent(p.filename)}${runId ? `?run=${encodeURIComponent(runId)}` : ""}`}
                className="block rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
              >
                <p className="font-medium text-clinova-deep">{p.title ?? p.filename}</p>
                <p className="mt-1 font-mono text-xs text-neutral">
                  {p.filename} · {p.char_count.toLocaleString("en-US")} chars
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
