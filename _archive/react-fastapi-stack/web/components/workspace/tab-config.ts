/**
 * The workspace's tabs, in pipeline order (Clinova Phase 5, Slice 15).
 *
 * Shared because three things need the same list and must not drift: the
 * workspace page renders them, the command palette makes them findable by
 * name, and the standalone routes redirect into them. Collapsing nine nav
 * entries into tabs immediately broke palette search for all nine -- the
 * palette derives its destinations from NAV_GROUPS, and they were no longer
 * there. One list, three consumers.
 */
export interface WorkspaceTabDef {
  key: string;
  label: string;
  /** The pre-Slice-15 standalone route, kept as a redirect into this tab. */
  legacyHref: string;
}

export const WORKSPACE_TABS: WorkspaceTabDef[] = [
  { key: "corpus", label: "Corpus", legacyHref: "/corpus" },
  { key: "quality", label: "Data Quality", legacyHref: "/quality" },
  { key: "evidence", label: "Evidence", legacyHref: "/evidence" },
  { key: "graph", label: "Knowledge Graph", legacyHref: "/knowledge-graph" },
  { key: "gaps", label: "Research Gaps", legacyHref: "/gaps" },
  { key: "challenger", label: "Gap Challenger", legacyHref: "/gap-challenger" },
  { key: "council", label: "Research Council", legacyHref: "/council" },
  { key: "modelling", label: "Computational Modelling", legacyHref: "/council/modelling" },
  { key: "proposals", label: "Proposals", legacyHref: "/proposals" },
];

export function workspaceHref(key: string): string {
  return `/workspace?tab=${key}`;
}

export function tabLabel(key: string | undefined): string | undefined {
  return WORKSPACE_TABS.find((t) => t.key === key)?.label;
}
