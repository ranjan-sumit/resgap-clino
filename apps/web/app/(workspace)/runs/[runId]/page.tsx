import { Fragment } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CountStatView } from "@/components/data/count-stat";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { StatusBadge } from "@/components/data/status-badge";
import { VersionFieldView } from "@/components/data/version-field";
import { EmptyState } from "@/components/data/empty-state";
import { ErrorState } from "@/components/data/error-state";
import { PageHero } from "@/components/shell/page-hero";
import { formatDuration } from "@/lib/format";
import { api, ApiError, type RunManifestView } from "@/lib/api";

function ManifestPanel({ manifest }: { manifest: RunManifestView }) {
  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Versions</h2>
        <div className="max-w-md divide-y divide-border/60 rounded-lg border border-border/60 bg-card px-4 shadow-card">
          {manifest.versions.map((v) => (
            <VersionFieldView key={v.key} field={v} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Quality gates</h2>
        <div className="flex flex-wrap gap-2">
          {manifest.quality_gates.map((g) => (
            <StatusBadge key={g.code} chip={g} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Token usage</h2>
        {manifest.token_usage.recorded ? (
          <div className="rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
            <p className="font-display text-2xl text-clinova-deep">
              {manifest.token_usage.total?.toLocaleString()} tokens
            </p>
            <p className="mt-1 text-xs text-neutral">
              {manifest.token_usage.n_calls_recorded} calls recorded
            </p>
            {manifest.token_usage.by_stage && (
              <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-neutral">
                {Object.entries(manifest.token_usage.by_stage).map(([stage, n]) => (
                  <div key={stage} className="flex justify-between gap-3">
                    <span>{stage}</span>
                    <span className="font-mono">{n.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm italic text-neutral">{manifest.token_usage.note}</p>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Run metadata</h2>
        <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
          <span className="text-neutral">Duration</span>
          <span className="text-clinova-deep">{formatDuration(manifest.run_duration_seconds)}</span>
          <span className="text-neutral">Academic search date</span>
          <span className="text-clinova-deep">{manifest.academic_search_date ?? "Not recorded"}</span>
          <span className="text-neutral">Search providers</span>
          <span className="text-clinova-deep">
            {manifest.search_providers.length > 0 ? manifest.search_providers.join(", ") : "None"}
          </span>
          <span className="text-neutral">Output artifacts</span>
          <span className="text-clinova-deep">
            {manifest.output_artifacts.length > 0 ? manifest.output_artifacts.join(", ") : "None"}
          </span>
        </div>
      </section>

      {Object.keys(manifest.parser_versions).length > 0 && (
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Parser versions</h2>
          <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-1.5 font-mono text-xs">
            {Object.entries(manifest.parser_versions).map(([parser, version]) => (
              <Fragment key={parser}>
                <span className="text-neutral">{parser}</span>
                <span className="text-clinova-deep">{version ?? "Not recorded"}</span>
              </Fragment>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ runId: string }>;
}): Promise<Metadata> {
  const { runId } = await params;
  try {
    const run = await api.getRun(runId);
    return { title: run.name };
  } catch {
    return { title: "Run" };
  }
}

export default async function RunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;

  let run;
  try {
    run = await api.getRun(runId);
  } catch (err) {
    if (err instanceof ApiError) {
      return <ErrorState title="Run not found" detail={err.message} retryHref="/runs" />;
    }
    throw err;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <Link href="/runs" className="text-sm text-neutral hover:text-clinova-deep hover:underline">
          &larr; All runs
        </Link>
      </div>

      <PageHero
        eyebrow="Run Detail"
        title={
          <span className="flex flex-wrap items-center gap-3">
            {run.name}
            <StatusBadge chip={run.status} />
          </span>
        }
        description={
          <span className="font-mono text-xs text-neutral">
            {run.run_id} · {run.created_at}
          </span>
        }
        actions={
          <Link
            href={`/runs/${run.run_id}/lineage`}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-clinova-deep hover:bg-secondary"
          >
            View lineage &rarr;
          </Link>
        }
      />

      {run.gate_blocked && (
        <Alert className="border-semantic-critical/30 bg-semantic-critical/5">
          <AlertDescription className="text-clinova-deep">
            <p className="font-medium">This run was blocked by a quality gate.</p>
            <ul className="mt-1 list-disc pl-5">
              {run.gate_block_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {run.warnings.length > 0 && (
        <Alert className="border-semantic-warning/30 bg-semantic-warning/5">
          <AlertDescription className="text-clinova-deep">
            <p className="font-medium">Warnings</p>
            <ul className="mt-1 list-disc pl-5">
              {run.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="manifest">Manifest</TabsTrigger>
          <TabsTrigger value="stages">Stages ({run.trace.length})</TabsTrigger>
          <TabsTrigger value="gaps">Gaps ({run.gaps.length})</TabsTrigger>
          <TabsTrigger value="papers">Papers ({run.papers.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-8 pt-4">
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Counts</h2>
            <div className="grid grid-cols-4 gap-4">
              {run.counts.map((c) => (
                <CountStatView key={c.key} stat={c} />
              ))}
            </div>
          </section>
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Confidence</h2>
            <div className="grid grid-cols-4 gap-4">
              {run.confidence.map((m) => (
                <ConfidenceStat key={m.key} measure={m} />
              ))}
            </div>
          </section>
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Versions</h2>
            <div className="max-w-md divide-y divide-border/60 rounded-lg border border-border/60 bg-card px-4 shadow-card">
              {run.versions.map((v) => (
                <VersionFieldView key={v.key} field={v} />
              ))}
            </div>
          </section>
        </TabsContent>

        <TabsContent value="manifest" className="pt-4">
          {run.manifest ? (
            <ManifestPanel manifest={run.manifest} />
          ) : (
            <EmptyState
              title="No manifest recorded"
              description="This run predates run-manifest capture (Epic 4.2). Manifest fields — versions, quality gates, token usage — are only recorded for runs created after that change."
            />
          )}
        </TabsContent>

        <TabsContent value="stages" className="pt-4">
          {run.trace.length === 0 ? (
            <EmptyState
              title="No stage trace recorded"
              description="This run predates pipeline trace capture, or the trace was empty."
            />
          ) : (
            <ol className="space-y-3 border-l border-border pl-4">
              {run.trace.map((t) => (
                <li key={t.index} className="relative rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
                  <span className="absolute -left-[21px] top-5 h-2 w-2 rounded-full bg-clinova-blue" />
                  <div className="flex items-center justify-between gap-3">
                    <p className="font-medium text-clinova-deep">{t.stage}</p>
                    <StatusBadge chip={t.status} size="sm" />
                  </div>
                  <p className="mt-1 text-xs text-neutral">
                    <span className="font-medium">In:</span> {t.inputs}
                  </p>
                  <p className="text-xs text-neutral">
                    <span className="font-medium">Out:</span> {t.outputs}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </TabsContent>

        <TabsContent value="gaps" className="pt-4">
          {run.gaps.length === 0 ? (
            <EmptyState title="No gaps recorded" description="No research gaps were extracted for this run." />
          ) : (
            <ul className="space-y-3">
              {run.gaps.map((g, i) => (
                <li key={g.gap_id ?? i} className="rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
                  <p className="font-medium text-clinova-deep">{g.title}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <StatusBadge chip={g.validation} size="sm" />
                    <StatusBadge chip={g.challenge} size="sm" />
                    <span className="text-xs text-neutral">Confidence: {g.confidence.display}</span>
                  </div>
                  {g.evidence_basis && <p className="mt-2 text-xs text-neutral">{g.evidence_basis}</p>}
                  {g.source && <p className="mt-1 text-xs text-neutral">Source: {g.source}</p>}
                </li>
              ))}
            </ul>
          )}
        </TabsContent>

        <TabsContent value="papers" className="pt-4">
          {run.papers.length === 0 ? (
            <EmptyState title="No papers recorded" description="No papers were attached to this run." />
          ) : (
            <ul className="space-y-2">
              {run.papers.map((p, i) => (
                <li key={i} className="rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
                  <p className="font-medium text-clinova-deep">{p.title ?? p.filename}</p>
                  <p className="mt-1 font-mono text-xs text-neutral">
                    {p.filename} · {p.char_count.toLocaleString()} chars
                  </p>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
