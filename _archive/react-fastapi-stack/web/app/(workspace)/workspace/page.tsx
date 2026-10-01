import type { Metadata } from "next";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Crosshair, Database, FileText, Lightbulb, ShieldCheck, Sigma, Target, Users, Workflow,
} from "lucide-react";
import { EmptyState } from "@/components/data/empty-state";
import { PageHero } from "@/components/shell/page-hero";
import { WorkspaceTabs, type WorkspaceTab } from "@/components/workspace/workspace-tabs";
import { WorkspaceStatStrip } from "@/components/workspace/workspace-stat-strip";
import { WorkspaceConfidenceStrip } from "@/components/workspace/workspace-confidence-strip";
import { Button } from "@/components/ui/button";
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

// One identity per tab, so the hero's well matches the section being read
// (the same mapping the pre-Slice-15 standalone screens would have used).
const TAB_ICONS: Record<string, LucideIcon> = {
  corpus: Database,
  quality: ShieldCheck,
  evidence: FileText,
  graph: Workflow,
  gaps: Target,
  challenger: Crosshair,
  council: Users,
  modelling: Sigma,
  proposals: Lightbulb,
};

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; run?: string }>;
}) {
  const { tab, run: runParam } = await searchParams;

  const project = await getSelectedProject();
  if (!project) {
    return (
      <EmptyState
        title={common.no_projects_title}
        description={common.no_projects_body}
        action={{ label: "Start a run", href: "/runs/new" }}
        secondaryAction={{ label: "Open Streamlit workspace", href: "http://localhost:8501" }}
      />
    );
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
      {/* The run identity is stated once for all 9 tabs; the hero's icon
          follows the active tab so the header matches the section read. */}
      <PageHero
        icon={TAB_ICONS[active.key] ?? Database}
        eyebrow={active.label}
        title={header.project_label}
        whisper={false}
        description={
          <span>
            {header.basis_note}{" "}
            <Link href={`/runs/${runId}`} className="text-clinova-deep underline">
              Run detail
            </Link>
          </span>
        }
        actions={
          <Button asChild size="sm">
            <Link href="/runs/new">Run analysis</Link>
          </Button>
        }
      />

      {/* One dense row of real stat tiles, not eight full cards -- keeps the
          original "fit the tab bar above the fold" density constraint
          (Streamlit fits its stats AND its tab bar above the fold; a full
          CountStatView grid here pushed the tab bar off the bottom of a
          1440x900 screen) while giving each tile the icon-well/hover/shadow
          language the rest of the app already uses. */}
      <WorkspaceStatStrip counts={header.counts} />

      <WorkspaceConfidenceStrip measures={header.confidence} />

      <div>
        <WorkspaceTabs tabs={TABS} active={active.key} />
        <div className="pt-6">{renderActive({ projectId: project.project_id, runId })}</div>
      </div>
    </div>
  );
}
