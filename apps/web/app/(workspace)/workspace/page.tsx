import type { Metadata } from "next";
import Link from "next/link";
import { EmptyState } from "@/components/data/empty-state";
import { WorkspaceTabs, type WorkspaceTab } from "@/components/workspace/workspace-tabs";
import { CorpusPanel } from "@/components/workspace/panels/corpus-panel";
import { QualityPanel } from "@/components/workspace/panels/quality-panel";
import { EvidencePanel } from "@/components/workspace/panels/evidence-panel";
import { GraphPanel } from "@/components/workspace/panels/graph-panel";
import { GapsPanel } from "@/components/workspace/panels/gaps-panel";
import { ChallengerPanel } from "@/components/workspace/panels/challenger-panel";
import { CouncilPanel } from "@/components/workspace/panels/council-panel";
import { ComputationalModellingPanel } from "@/components/workspace/panels/modelling-panel";
import { ProposalsPanel } from "@/components/workspace/panels/proposals-panel";
import { api } from "@/lib/api";
import { getSelectedProject } from "@/lib/project";
import { common } from "@/lib/copy";
import { WORKSPACE_TABS, tabLabel } from "@/components/workspace/tab-config";
import type { PanelProps } from "@/components/workspace/panel-props";

// The browser tab must still say which section you are reading. Without
// this every one of the nine tabs titled itself "Workspace", so bookmarks
// and open tabs became indistinguishable -- a real thing the nine separate
// routes used to get for free.
export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}): Promise<Metadata> {
  const { tab } = await searchParams;
  return { title: tabLabel(tab) ?? WORKSPACE_TABS[0].label };
}

// Render map, keyed by the shared tab config so the palette, the redirects
// and this page cannot disagree about which tabs exist.
const RENDERERS: Record<string, (p: PanelProps) => React.ReactNode> = {
  corpus: (p) => <CorpusPanel {...p} />,
  quality: (p) => <QualityPanel {...p} />,
  evidence: (p) => <EvidencePanel {...p} />,
  graph: (p) => <GraphPanel {...p} />,
  gaps: (p) => <GapsPanel {...p} />,
  challenger: (p) => <ChallengerPanel {...p} />,
  council: (p) => <CouncilPanel {...p} />,
  modelling: (p) => <ComputationalModellingPanel {...p} />,
  proposals: (p) => <ProposalsPanel {...p} />,
};

const TABS: WorkspaceTab[] = WORKSPACE_TABS.map(({ key, label }) => ({ key, label }));

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; run?: string }>;
}) {
  const { tab, run: runParam } = await searchParams;

  const project = await getSelectedProject();
  if (!project) {
    return <EmptyState title={common.no_projects_title} description={common.no_projects_body} />;
  }

  const header = await api.workspaceHeader(project.project_id, runParam);
  if (header.empty_reason || !header.basis_run) {
    return (
      <EmptyState
        title={common.no_runs_title}
        description={header.empty_reason ?? common.no_runs_body}
        action={{ label: "Start a run", href: "/runs/new" }}
      />
    );
  }

  // An unknown ?run= falls back to the newest run server-side, so pin the
  // tabs to the run the API actually resolved rather than to the raw param
  // -- otherwise nine panels would each re-resolve it independently.
  const runId = header.basis_run.run_id;
  const active = TABS.find((t) => t.key === tab) ?? TABS[0];
  const renderActive = RENDERERS[active.key];

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {/* Compact header. The old per-screen PageHero cost ~130px to repeat
          the name of the nav item just clicked; here the run identity is the
          only thing worth that space, and it is stated once for all 9 tabs. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div>
          <h1 className="font-display text-2xl text-clinova-deep">{header.project_label}</h1>
          <p className="mt-0.5 text-sm text-neutral">
            {header.basis_note}{" "}
            <Link href={`/runs/${runId}`} className="text-clinova-deep underline">
              Run detail
            </Link>
          </p>
        </div>
        <Link
          href="/runs/new"
          className="rounded-md bg-clinova-deep px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-clinova-deep/90"
        >
          Run analysis
        </Link>
      </div>

      {/* One dense strip, not eight cards. Streamlit fits its stats AND its
          tab bar above the fold; the card grid here pushed the tab bar off
          the bottom of a 1440x900 screen. */}
      <div className="flex flex-wrap items-stretch divide-x divide-border/60 overflow-hidden rounded-lg border border-border/60 bg-card shadow-card">
        {header.counts.map((c) => (
          <div key={c.key} className="flex-1 px-4 py-2.5" title={c.source}>
            <p className="font-display text-xl leading-tight text-clinova-deep">{c.display}</p>
            <p className="text-[10px] uppercase tracking-wide text-neutral">{c.label}</p>
          </div>
        ))}
      </div>

      <ConfidenceStrip measures={header.confidence} />

      <div>
        <WorkspaceTabs tabs={TABS} active={active.key} />
        <div className="pt-6">{renderActive({ projectId: project.project_id, runId })}</div>
      </div>
    </div>
  );
}

/**
 * Recorded confidence values inline; unmeasured ones folded into a
 * disclosure that still carries every reason.
 *
 * Before this, four of five tiles said "Not recorded" over a four-line
 * justification each, so the largest thing on the landing screen was an
 * explanation of what had NOT been measured. Being honest about absent data
 * is right; giving absence more room than presence is an editorial mistake,
 * not an honesty requirement. Nothing is hidden -- it is one click away and
 * every basis string is still rendered in full.
 */
function ConfidenceStrip({ measures }: { measures: { key: string; label: string; display: string; basis: string; recorded: boolean }[] }) {
  const recorded = measures.filter((m) => m.recorded);
  const unmeasured = measures.filter((m) => !m.recorded);

  if (measures.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      {recorded.map((m) => (
        <span key={m.key} className="inline-flex items-baseline gap-1.5" title={m.basis}>
          <span className="text-xs uppercase tracking-wide text-neutral">{m.label}</span>
          <span className="font-display text-lg text-clinova-deep">{m.display}</span>
        </span>
      ))}

      {unmeasured.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-xs text-neutral underline decoration-dotted underline-offset-4 hover:text-clinova-deep">
            {unmeasured.length} of {measures.length} confidence measures not recorded — why
          </summary>
          <ul className="mt-2 space-y-1.5 rounded-md border border-border/60 bg-card p-3 shadow-card">
            {unmeasured.map((m) => (
              <li key={m.key} className="text-xs leading-relaxed">
                <span className="font-medium text-slate-700">{m.label}:</span>{" "}
                <span className="text-neutral">{m.basis}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
