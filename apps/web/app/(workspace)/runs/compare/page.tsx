import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { StatusBadge } from "@/components/data/status-badge";
import { MetricDelta } from "@/components/data/metric-delta";
import { EmptyState } from "@/components/data/empty-state";
import { ErrorState } from "@/components/data/error-state";
import { ComparePicker } from "@/components/runs/compare-picker";
import { PromoteCandidateButton } from "@/components/runs/promote-candidate-button";
import { PageHero } from "@/components/shell/page-hero";
import { api, ApiError, type RunComparison } from "@/lib/api";

function DiffList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-neutral">
        {title} ({items.length})
      </p>
      {items.length === 0 ? (
        <p className="text-sm italic text-neutral">None</p>
      ) : (
        <ul className="space-y-1 text-sm text-clinova-deep">
          {items.map((item, i) => (
            <li key={i} className="truncate" title={item}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ComparisonView({ comparison }: { comparison: RunComparison }) {
  const { promotion } = comparison;

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-xl border border-border/60 bg-card p-6 shadow-raised">
        <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-clinova-cyan/10 blur-2xl" aria-hidden />
        <div className="relative flex items-start gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-clinova-deep to-clinova-blue text-white shadow-glow-sm">
            <ShieldCheck className="h-5 w-5" aria-hidden />
          </div>
          <div className="flex-1">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">Promotion gate</h2>
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge chip={promotion.status} />
              {promotion.candidate_artifact_id && (
                <span className="font-mono text-xs text-neutral">{promotion.candidate_artifact_id}</span>
              )}
            </div>
            {(promotion.blocking_reasons.length > 0 || !promotion.can_evaluate) && (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-neutral">
                {!promotion.can_evaluate && <li>{promotion.status.reason}</li>}
                {promotion.blocking_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            {promotion.warnings.length > 0 && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-semantic-warning">
                {promotion.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
            <PromoteCandidateButton candidateRunId={comparison.candidate.run_id} promotion={promotion} />
          </div>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Evaluation metrics</h2>
        {comparison.metrics_note && <p className="mb-3 text-sm italic text-neutral">{comparison.metrics_note}</p>}
        <div className="overflow-hidden rounded-lg border border-border/60 bg-card shadow-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                <TableHead>Baseline</TableHead>
                <TableHead>Candidate</TableHead>
                <TableHead>Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comparison.metrics.map((m) => (
                <TableRow key={m.key}>
                  <TableCell className="text-sm text-clinova-deep">{m.label}</TableCell>
                  <TableCell className="font-mono text-sm text-neutral">{m.baseline_display}</TableCell>
                  <TableCell className="font-mono text-sm text-neutral">{m.candidate_display}</TableCell>
                  <TableCell>
                    <MetricDelta metric={m} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Content diffs</h2>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
            <p className="mb-3 font-medium text-clinova-deep">Papers</p>
            <p className="mb-3 text-xs text-neutral">
              {comparison.papers.summary} · {comparison.papers.common_count} unchanged
            </p>
            <div className="grid grid-cols-2 gap-4">
              <DiffList title="Added" items={comparison.papers.added} />
              <DiffList title="Removed" items={comparison.papers.removed} />
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
            <p className="mb-3 font-medium text-clinova-deep">Evidence objects</p>
            <p className="text-sm text-neutral">
              {comparison.evidence.count_baseline} → {comparison.evidence.count_candidate}{" "}
              ({comparison.evidence.delta >= 0 ? "+" : ""}
              {comparison.evidence.delta})
            </p>
          </div>

          <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
            <p className="mb-3 font-medium text-clinova-deep">Knowledge graph</p>
            <p className="mb-3 text-xs text-neutral">
              {comparison.graph.entities_common_count} entities and{" "}
              {comparison.graph.relationships_common_count} relationships unchanged
            </p>
            <div className="grid grid-cols-2 gap-4">
              <DiffList title="Entities added" items={comparison.graph.entities_added} />
              <DiffList title="Entities removed" items={comparison.graph.entities_removed} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-4">
              <DiffList
                title="Relationships added"
                items={comparison.graph.relationships_added.map((r) => r.join(" — "))}
              />
              <DiffList
                title="Relationships removed"
                items={comparison.graph.relationships_removed.map((r) => r.join(" — "))}
              />
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
            <p className="mb-3 font-medium text-clinova-deep">Proposals</p>
            <p className="text-sm text-neutral">
              {comparison.proposals.summary} · {comparison.proposals.common_count} unchanged
            </p>
          </div>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Research gaps</h2>
        <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <p className="mb-3 text-xs text-neutral">{comparison.gaps.common_count} gaps unchanged</p>
          <div className="grid grid-cols-2 gap-4">
            <DiffList title="Added" items={comparison.gaps.added} />
            <DiffList title="Removed" items={comparison.gaps.removed} />
          </div>
          {comparison.gaps.confidence_changes.length > 0 && (
            <div className="mt-5 space-y-3 border-t border-border pt-4">
              <p className="text-xs font-medium uppercase tracking-wide text-neutral">Confidence changes</p>
              {comparison.gaps.confidence_changes.map((c, i) => (
                <div key={i} className="text-sm">
                  <p className="font-medium text-clinova-deep">{c.title}</p>
                  <p className="text-xs text-neutral">
                    {c.confidence_baseline ?? "Not recorded"} → {c.confidence_candidate ?? "Not recorded"}
                  </p>
                  <p className="mt-1 text-xs text-neutral">{c.explanation}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Manifest diff</h2>
        <div className="overflow-hidden rounded-lg border border-border/60 bg-card shadow-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Baseline</TableHead>
                <TableHead>Candidate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comparison.manifest_diff.map((d) => (
                <TableRow key={d.key} className={d.changed ? "bg-clinova-light/10" : undefined}>
                  <TableCell className="text-sm text-clinova-deep">{d.label}</TableCell>
                  <TableCell className="font-mono text-xs text-neutral">{d.baseline ?? "Not recorded"}</TableCell>
                  <TableCell className="font-mono text-xs text-neutral">{d.candidate ?? "Not recorded"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  );
}

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ baseline?: string; candidate?: string }>;
}) {
  const { baseline, candidate } = await searchParams;
  const { runs } = await api.listRuns();

  let comparison: RunComparison | null = null;
  let error: string | null = null;

  if (baseline && candidate && baseline !== candidate) {
    try {
      comparison = await api.compare(baseline, candidate);
    } catch (err) {
      error = err instanceof ApiError ? err.message : "Failed to load comparison.";
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHero
        eyebrow="Engineering"
        title="Compare"
        description="Compare a baseline and a candidate run across metrics, content, and the promotion gate."
      />

      {runs.length < 2 ? (
        <EmptyState
          title="Need at least two runs to compare"
          description="Come back once more than one run has been recorded."
          action={{ label: "View runs", href: "/runs" }}
        />
      ) : (
        <ComparePicker runs={runs} initialBaseline={baseline} initialCandidate={candidate} />
      )}

      {error && <ErrorState title="Could not load comparison" detail={error} />}
      {comparison && (
        <>
          <div className="flex items-center gap-2 text-sm text-neutral">
            <Link href={`/runs/${comparison.baseline.run_id}`} className="text-clinova-deep hover:underline">
              {comparison.baseline.name}
            </Link>
            <span>vs.</span>
            <Link href={`/runs/${comparison.candidate.run_id}`} className="text-clinova-deep hover:underline">
              {comparison.candidate.name}
            </Link>
          </div>
          <ComparisonView comparison={comparison} />
        </>
      )}
    </div>
  );
}
