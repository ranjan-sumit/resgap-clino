import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight, GitCompare, LayoutDashboard } from "lucide-react";
import { CountStatView } from "@/components/data/count-stat";
import { ConfidenceStat } from "@/components/data/confidence-stat";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { PageHero } from "@/components/shell/page-hero";
import { api } from "@/lib/api";
import { getSelectedProject } from "@/lib/project";
import { common } from "@/lib/copy";

export const metadata: Metadata = { title: "Dashboard" };

const RECENT_LIMIT_OPTIONS = [5, 10, 20] as const;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ run?: string; recent?: string }>;
}) {
  const { run: runId, recent } = await searchParams;
  // Bounded client-side too, in case of a hand-edited URL -- the API also
  // clamps this (Query(..., ge=1, le=20)), so an out-of-range value here
  // would just be silently re-clamped server-side, not rejected.
  const recentLimit = RECENT_LIMIT_OPTIONS.includes(Number(recent) as (typeof RECENT_LIMIT_OPTIONS)[number])
    ? Number(recent)
    : RECENT_LIMIT_OPTIONS[0];

  const project = await getSelectedProject();

  if (!project) {
    return (
      <EmptyState
        title="No projects yet"
        description={common.no_projects_body}
        action={{ label: "Start a run", href: "/runs/new" }}
        secondaryAction={{ label: "Open Streamlit workspace", href: "http://localhost:8501" }}
      />
    );
  }

  const dashboard = await api.getDashboard(project.project_id, runId, recentLimit);

  if (dashboard.empty_reason) {
    return (
      <EmptyState
        title="No runs in this project yet"
        description={dashboard.empty_reason}
        action={{ label: "Start a run", href: "/runs/new" }}
      />
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-10">
      <PageHero
        icon={LayoutDashboard}
        eyebrow="Project Dashboard"
        title={dashboard.project_label}
        description={
          dashboard.basis_run && (
            <>
              {dashboard.basis_note}{" "}
              <Link href={`/runs/${dashboard.basis_run.run_id}`} className="text-clinova-deep underline">
                View run
              </Link>
            </>
          )
        }
      />

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Corpus at a glance</h2>
        <div className="grid grid-cols-4 gap-4">
          {dashboard.counts.map((c) => (
            <CountStatView key={c.key} stat={c} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Confidence</h2>
        <div className="grid grid-cols-5 gap-4">
          {dashboard.confidence.map((m) => (
            <ConfidenceStat key={m.key} measure={m} />
          ))}
        </div>
      </section>

      {/* What changed since the previous run. Built from the same
          compare_runs() the Compare screen uses, so the two can never
          disagree. Absent (not zeroed) for a single-run project, where
          there is genuinely nothing to compare against. */}
      {dashboard.delta && (
        <section className="rounded-xl border border-border/60 bg-secondary/40 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral">
              <GitCompare className="h-3.5 w-3.5 text-clinova-blue" aria-hidden />
              Since the previous run
            </h2>
            <Link
              href={dashboard.delta.compare_href}
              className="text-xs text-clinova-deep hover:underline"
            >
              Full comparison &rarr;
            </Link>
          </div>
          <p className="mt-1 text-xs text-neutral">
            {dashboard.delta.previous_run.name} &rarr; {dashboard.delta.current_run.name}
          </p>

          {dashboard.delta.unchanged ? (
            <p className="mt-3 text-sm text-neutral">
              Nothing measurable changed between these two runs.
            </p>
          ) : (
            <div className="mt-4 grid grid-cols-4 gap-4">
              {[
                ["Gaps", dashboard.delta.gaps_added.length, dashboard.delta.gaps_removed.length],
                ["Papers", dashboard.delta.papers_added.length, dashboard.delta.papers_removed.length],
                ["Graph entities", dashboard.delta.entities_added_count, dashboard.delta.entities_removed_count],
                ["Proposals", dashboard.delta.proposals_added_count, dashboard.delta.proposals_removed_count],
              ].map(([label, added, removed]) => (
                <div key={label as string}>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-neutral">
                    {label as string}
                  </p>
                  <p className="mt-0.5 font-mono text-sm">
                    <span className={(added as number) > 0 ? "text-semantic-success" : "text-neutral"}>
                      +{added as number}
                    </span>
                    <span className="mx-1 text-neutral/40">/</span>
                    <span className={(removed as number) > 0 ? "text-semantic-critical" : "text-neutral"}>
                      &minus;{removed as number}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          )}

          {dashboard.delta.gaps_added.length > 0 && (
            <div className="mt-4 border-t border-border/60 pt-3">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-neutral">
                New gaps ({dashboard.delta.gaps_added.length})
              </p>
              <ul className="list-disc space-y-1 pl-4 text-xs text-foreground">
                {dashboard.delta.gaps_added.slice(0, 5).map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <section className="grid grid-cols-2 gap-8">
        <div>
          <h2 className="mb-3 flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wider text-neutral">
            Top research opportunities
            <span className="text-xs font-normal normal-case tracking-normal text-neutral/70">
              {dashboard.top_opportunities.length}
            </span>
          </h2>
          {dashboard.top_opportunities.length === 0 ? (
            <EmptyState
              title="No open opportunities yet"
              description="Gaps reach this list once the Gap Challenger stage assigns them an actionable status."
            />
          ) : (
            <ul className="space-y-2">
              {dashboard.top_opportunities.map((g) => (
                <li
                  key={g.gap_id ?? g.title}
                  className="group rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
                >
                  <Link
                    href={`/runs/${g.run_id}`}
                    className="flex items-start justify-between gap-2 font-medium text-clinova-deep hover:underline"
                  >
                    {g.title}
                    <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-clinova-cyan opacity-0 transition-opacity group-hover:opacity-100" />
                  </Link>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <StatusBadge chip={g.validation} size="sm" />
                    <StatusBadge chip={g.challenge} size="sm" />
                  </div>
                  {g.evidence_basis && <p className="mt-2 text-xs text-neutral">{g.evidence_basis}</p>}
                </li>
              ))}
            </ul>
          )}
          {dashboard.n_excluded_insufficient_evidence > 0 && (
            <p className="mt-3 text-xs text-neutral">
              {dashboard.n_excluded_insufficient_evidence} further candidate gap(s) could not be assessed —
              insufficient search coverage.
            </p>
          )}
        </div>

        <div>
          <div className="mb-3 flex items-baseline justify-between gap-2">
            <h2 className="flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wider text-neutral">
              Recent runs
              <span className="text-xs font-normal normal-case tracking-normal text-neutral/70">
                {dashboard.recent_runs.length}
              </span>
            </h2>
            <div className="flex items-center gap-1 text-[11px] text-neutral">
              Show
              {RECENT_LIMIT_OPTIONS.map((n) => (
                <Link
                  key={n}
                  href={`/dashboard?${runId ? `run=${encodeURIComponent(runId)}&` : ""}recent=${n}`}
                  className={
                    n === recentLimit
                      ? "rounded px-1.5 py-0.5 font-semibold text-clinova-deep underline"
                      : "rounded px-1.5 py-0.5 hover:text-clinova-deep hover:underline"
                  }
                >
                  {n}
                </Link>
              ))}
            </div>
          </div>
          <ul className="space-y-2">
            {dashboard.recent_runs.map((r) => (
              <li
                key={r.run_id}
                className="group rounded-lg border border-border/60 bg-card p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
              >
                <div className="flex items-center justify-between">
                  <Link href={`/runs/${r.run_id}`} className="font-medium text-clinova-deep hover:underline">
                    {r.name}
                  </Link>
                  <StatusBadge chip={r.status} size="sm" />
                </div>
                <p className="mt-1 font-mono text-xs text-neutral">
                  {r.run_id.slice(0, 8)} · {r.n_papers}p · {r.n_gaps}g · {r.n_proposals}pr
                </p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section>
        <h2 className="mb-3 flex items-baseline gap-2 text-xs font-semibold uppercase tracking-wider text-neutral">
          Research activity
          <span className="text-xs font-normal normal-case tracking-normal text-neutral/70">
            {dashboard.activity.length}
          </span>
        </h2>
        <ol className="space-y-3 border-l-2 border-clinova-light/30 pl-4">
          {dashboard.activity.map((a, i) => (
            <li key={`${a.kind}-${i}`} className="relative">
              <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-clinova-cyan" />
              <Link href={a.href} className="text-sm font-medium text-clinova-deep hover:underline">
                {a.title}
              </Link>
              <p className="text-xs text-neutral">
                {a.detail} · <span className="font-mono">{a.timestamp}</span>
              </p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
