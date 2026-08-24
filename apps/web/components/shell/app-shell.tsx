import type { ReactNode } from "react";
import { SideNav } from "@/components/shell/side-nav";
import { TopBar } from "@/components/shell/top-bar";
import type { ProjectSummary } from "@/lib/api";

export function AppShell({
  productName,
  projects,
  children,
}: {
  productName: string;
  projects: ProjectSummary[];
  children: ReactNode;
}) {
  return (
    <div className="flex">
      <SideNav productName={productName} />
      <div className="flex min-h-screen flex-1 flex-col">
        <TopBar projects={projects} />
        <main className="flex-1 bg-surface px-10 py-10">{children}</main>
      </div>
    </div>
  );
}
