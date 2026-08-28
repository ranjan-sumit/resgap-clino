import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { getBranding } from "@/lib/branding";
import { getSelectedProject } from "@/lib/project";
import { api } from "@/lib/api";

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const [{ theme }, projects, selected] = await Promise.all([
    getBranding(),
    api.listProjects(),
    getSelectedProject(),
  ]);

  return (
    <AppShell
      productName={theme.product_name}
      projects={projects}
      selectedProjectId={selected?.project_id}
    >
      {children}
    </AppShell>
  );
}
