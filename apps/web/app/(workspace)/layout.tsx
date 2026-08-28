import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { getBranding } from "@/lib/branding";
import { getSelectedProject } from "@/lib/project";
import { api } from "@/lib/api";

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const [{ theme }, projects, selected, runList] = await Promise.all([
    getBranding(),
    api.listProjects(),
    getSelectedProject(),
    // Feeds the sidebar's always-visible run switcher, so every screen has it
    // -- the persistent run history Streamlit had and this app did not.
    // runOptions, NOT listRuns: listRuns loads each run's full JSONB plus its
    // manifest to derive status/versions the switcher never shows, which put
    // ~6s in front of EVERY page once this moved into the layout.
    api.runOptions(25).catch(() => [] as Awaited<ReturnType<typeof api.runOptions>>),
  ]);

  const runs = runList.filter((r) => !selected || r.project_id === selected.project_id);

  return (
    <AppShell
      productName={theme.product_name}
      projects={projects}
      selectedProjectId={selected?.project_id}
      runs={runs}
    >
      {children}
    </AppShell>
  );
}
