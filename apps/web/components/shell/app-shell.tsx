import type { ReactNode } from "react";
import { SideNav } from "@/components/shell/side-nav";
import { TopBar } from "@/components/shell/top-bar";
import type { ProjectSummary } from "@/lib/api";

export function AppShell({
  productName,
  projects,
  selectedProjectId,
  children,
}: {
  productName: string;
  projects: ProjectSummary[];
  selectedProjectId?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start">
      <SideNav productName={productName} />
      <div className="flex min-h-screen flex-1 flex-col">
        <TopBar projects={projects} selectedProjectId={selectedProjectId} />
        <main className="flex-1 bg-surface px-10 py-10">{children}</main>
      </div>
    </div>
  );
}
