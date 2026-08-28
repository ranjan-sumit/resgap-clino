// Exact left-nav structure per 02-ux-specification.md §4.2. Unbuilt
// items render muted+non-clickable with a "Later" marker rather than
// being omitted (thin product) or linked to a 404 (worse) -- see
// side-nav.tsx.
export interface NavItem {
  label: string;
  href?: string;
  status: "live" | "planned";
}

export interface NavGroup {
  label: string;
  items: NavItem[];
  hidden?: boolean;
  hiddenReason?: string;
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { label: "Dashboard", href: "/dashboard", status: "live" },
      { label: "Projects", status: "planned" },
    ],
  },
  {
    label: "Research",
    items: [
      { label: "Corpus", href: "/corpus", status: "live" },
      { label: "Evidence", href: "/evidence", status: "live" },
      { label: "Knowledge Graph", href: "/knowledge-graph", status: "live" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "Research Gaps", href: "/gaps", status: "live" },
      { label: "Gap Challenger", href: "/gap-challenger", status: "live" },
      { label: "Research Council", href: "/council", status: "live" },
      // Deep-links straight to the Council page's modelling tab. It lived
      // only as a tab label before, so anyone scanning the sidebar for
      // "computational modelling" found nothing and concluded it was missing.
      { label: "Computational Modelling", href: "/council/modelling", status: "live" },
      { label: "Proposals", href: "/proposals", status: "live" },
    ],
  },
  {
    label: "Engineering",
    items: [
      // First entry in the group: starting a run is the primary verb of
      // this product, and it had no entry point in the web app at all.
      { label: "New Run", href: "/runs/new", status: "live" },
      { label: "Runs", href: "/runs", status: "live" },
      { label: "Compare", href: "/runs/compare", status: "live" },
      { label: "Versions", href: "/versions", status: "live" },
      { label: "Experiments", status: "planned" },
      { label: "Lineage", href: "/runs/lineage", status: "live" },
    ],
  },
  {
    label: "Governance",
    hidden: true,
    hiddenReason: "Phase 6, conditional on a real second user (AD-2 / PRD FR-33).",
    items: [
      { label: "Models", status: "planned" },
      { label: "Prompts", status: "planned" },
      { label: "Agents", status: "planned" },
      { label: "Policies", status: "planned" },
      { label: "Audit", status: "planned" },
    ],
  },
  {
    label: "Settings",
    items: [{ label: "Settings", href: "/settings", status: "live" }],
  },
];
