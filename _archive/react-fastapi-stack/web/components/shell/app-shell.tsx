import type { ReactNode } from "react";
import { SideNav } from "@/components/shell/side-nav";
import { TopBar } from "@/components/shell/top-bar";
import { PageFade } from "@/components/shell/page-fade";
import type { ProjectSummary, RunOption } from "@/lib/api";

export function AppShell({
  wordmark,
  descriptor,
  projects,
  selectedProjectId,
  runs,
  children,
}: {
  wordmark: string;
  descriptor: string;
  projects: ProjectSummary[];
  selectedProjectId?: string;
  runs: RunOption[];
  children: ReactNode;
}) {
  return (
    <div className="flex items-start">
      <SideNav wordmark={wordmark} descriptor={descriptor} runs={runs} />
      <div className="flex min-h-screen flex-1 flex-col">
        <TopBar wordmark={wordmark} descriptor={descriptor} projects={projects} selectedProjectId={selectedProjectId} />
        <main className="flex-1 bg-surface px-10 py-10 dark:bg-dark-background">
          <PageFade>{children}</PageFade>
        </main>
      </div>
    </div>
  );
}
