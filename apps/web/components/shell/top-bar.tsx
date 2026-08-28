"use client";

import { useRouter } from "next/navigation";
import { Bell, User } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CommandPalette } from "@/components/shell/command-palette";
import { PROJECT_COOKIE } from "@/lib/project-cookie";
import type { ProjectSummary } from "@/lib/api";

export function TopBar({
  projects,
  selectedProjectId,
}: {
  projects: ProjectSummary[];
  selectedProjectId?: string;
}) {
  const router = useRouter();

  // Writes the selection the server-side getSelectedProject() reads, then
  // re-renders the current Server Component page against the new project.
  // Previously this <Select> had no handler at all -- purely decorative.
  const selectProject = (projectId: string) => {
    document.cookie = `${PROJECT_COOKIE}=${encodeURIComponent(projectId)}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  };

  return (
    <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center justify-between border-b border-border/70 bg-white/80 px-8 backdrop-blur-sm">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-accent-line opacity-40" aria-hidden />
      <div className="flex items-center gap-4">
        {projects.length > 0 ? (
          <Select value={selectedProjectId ?? projects[0].project_id} onValueChange={selectProject}>
            <SelectTrigger className="h-8 w-[220px] border-border/70 text-sm shadow-sm">
              <SelectValue placeholder="Select project" />
            </SelectTrigger>
            <SelectContent>
              {projects.map((p) => (
                <SelectItem key={p.project_id} value={p.project_id}>
                  {p.label} ({p.n_runs} runs)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-sm italic text-neutral">No projects yet</span>
        )}
        <span className="h-4 w-px bg-border" />
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help font-mono text-xs italic text-neutral">Corpus: Not recorded</span>
          </TooltipTrigger>
          <TooltipContent>This pipeline does not version its input corpus yet.</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help font-mono text-xs italic text-neutral">Pipeline: Not recorded</span>
          </TooltipTrigger>
          <TooltipContent>No pipeline version constant is recorded by app.py&apos;s manifest write.</TooltipContent>
        </Tooltip>
      </div>

      <div className="flex items-center gap-3">
        <CommandPalette />
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="flex h-8 w-8 cursor-not-allowed items-center justify-center rounded-md text-neutral/40">
              <Bell className="h-4 w-4" aria-hidden />
            </span>
          </TooltipTrigger>
          <TooltipContent>Notifications are not built in this slice yet.</TooltipContent>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-clinova-deep to-clinova-blue text-white shadow-glow-sm transition-transform hover:scale-105">
              <User className="h-4 w-4" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem disabled>Local workspace — authentication arrives in Phase 6</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
