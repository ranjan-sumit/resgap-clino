import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { getBranding } from "@/lib/branding";
import { api } from "@/lib/api";

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const [{ theme }, projects] = await Promise.all([getBranding(), api.listProjects()]);

  return (
    <AppShell productName={theme.product_name} projects={projects}>
      {children}
    </AppShell>
  );
}
