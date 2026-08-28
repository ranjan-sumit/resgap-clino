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

// Slice 15 restructure. The nav previously listed nine run-scoped screens as
// nine separate destinations, so reading a gap and then its supporting graph
// meant two full navigations and losing your place. Those nine are now tabs
// inside /workspace (which the sidebar's run history scopes to one run), and
// the sidebar keeps only what is genuinely NOT run-scoped: starting a run,
// and comparing/tracing across runs.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { label: "Workspace", href: "/workspace", status: "live" },
      { label: "Dashboard", href: "/dashboard", status: "live" },
      { label: "Projects", status: "planned" },
    ],
  },
  {
    label: "Across runs",
    items: [
      // Starting a run is the primary verb of this product. Streamlit had it
      // above the fold; here it is the first sidebar entry that is not the
      // workspace itself, and it also appears as a button on the workspace.
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
