"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bell, ChevronDown, Folder, History } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CommandPalette } from "@/components/shell/command-palette";
import { shell } from "@/lib/copy";
import { PROJECT_COOKIE } from "@/lib/project-cookie";
import type { ProjectSummary } from "@/lib/api";

export function TopBar({
  wordmark,
  descriptor,
  projects,
  selectedProjectId,
}: {
  wordmark: string;
  descriptor: string;
  projects: ProjectSummary[];
  selectedProjectId?: string;
}) {
  const router = useRouter();
  const selected = projects.find((p) => p.project_id === selectedProjectId) ?? projects[0];

  // Writes the selection the server-side getSelectedProject() reads, then
  // re-renders the current Server Component page against the new project.
  // Previously this <Select> had no handler at all -- purely decorative.
  const selectProject = (projectId: string) => {
    document.cookie = `${PROJECT_COOKIE}=${encodeURIComponent(projectId)}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  };

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center justify-between border-b border-border/60 bg-white/75 px-8 backdrop-blur-xl dark:border-dark-border dark:bg-dark-background/75">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-accent-line opacity-40" aria-hidden />
      <div className="flex items-center gap-3">
        <DropdownMenu>
          <DropdownMenuTrigger className="flex h-8 max-w-[280px] items-center gap-2 rounded-lg border border-border/70 bg-white pl-2.5 pr-2 text-sm font-medium shadow-sm outline-none transition-colors hover:border-clinova-cyan/50 focus-visible:ring-2 focus-visible:ring-clinova-cyan/50 focus-visible:ring-offset-1 dark:border-dark-border dark:bg-dark-card dark:text-dark-foreground">
            <Folder className="h-3.5 w-3.5 shrink-0 text-neutral dark:text-dark-muted-foreground" aria-hidden />
            <span className="truncate">{selected?.label ?? "Select project"}</span>
            <span className="shrink-0 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-neutral dark:bg-dark-secondary dark:text-dark-muted-foreground">
              {selected?.n_runs ?? 0} runs
            </span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-neutral/60 dark:text-dark-muted-foreground" aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64 rounded-lg border-border/70 shadow-raised">
            <DropdownMenuRadioGroup value={selected?.project_id} onValueChange={selectProject}>
              {projects.map((p) => (
                <DropdownMenuRadioItem
                  key={p.project_id}
                  value={p.project_id}
                  className="cursor-pointer rounded-md"
                >
                  <span className="truncate">{p.label}</span>
                  <span className="ml-auto pl-3 text-xs text-neutral">{p.n_runs}</span>
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        {/* Was two permanent "Corpus: Not recorded" / "Pipeline: Not recorded"
            chips in the top bar of all 19 screens. Both are structurally
            always absent (app.py's manifest write never sets them), so they
            never changed and never will until that changes -- an unchanging
            caveat repeated on every screen is noise, not honesty. The same
            fields are still shown in full, with their reasons, on Versions
            and on Run Detail's Manifest tab. This keeps the signal and makes
            it a way to go read them. */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Link
              href="/versions"
              className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-neutral transition-colors hover:bg-secondary hover:text-clinova-deep dark:text-dark-muted-foreground dark:hover:bg-dark-secondary dark:hover:text-dark-foreground"
            >
              <History className="h-3.5 w-3.5" aria-hidden />
              Versions: not recorded
            </Link>
          </TooltipTrigger>
          <TooltipContent>
            Neither the input-corpus version nor the pipeline version is written by this pipeline&apos;s
            manifest yet. Open Versions for the full list and the reason for each.
          </TooltipContent>
        </Tooltip>
      </div>

      <div className="flex items-center gap-3">
        <CommandPalette projectId={selected?.project_id} />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-secondary/60 px-2 py-0.5 text-[11px] font-medium text-neutral dark:border-dark-border dark:bg-dark-secondary/60 dark:text-dark-muted-foreground">
          <span className="relative flex h-2 w-2" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-semantic-success opacity-50" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-semantic-success" />
          </span>
          {shell.environment}
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="flex h-8 w-8 cursor-not-allowed items-center justify-center rounded-md text-neutral/30 dark:text-dark-muted-foreground/30">
              <Bell className="h-4 w-4" aria-hidden />
            </span>
          </TooltipTrigger>
          <TooltipContent>Notifications are not built in this slice yet.</TooltipContent>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger className="flex h-8 w-8 items-center justify-center rounded-full bg-clinova-blue text-xs font-semibold text-white outline-none transition-shadow hover:ring-2 hover:ring-clinova-cyan/40 focus-visible:ring-2 focus-visible:ring-clinova-cyan/50 focus-visible:ring-offset-1 dark:bg-dark-primary dark:text-dark-primary-foreground">
            {shell.user_initial}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="rounded-lg border-border/70 shadow-raised">
            <DropdownMenuLabel className="px-2 py-1.5">
              <span className="block text-sm font-semibold text-clinova-deep dark:text-dark-foreground">{wordmark}</span>
              <span className="block text-[11px] font-normal text-neutral dark:text-dark-muted-foreground">{descriptor}</span>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled>Local workspace — authentication arrives in Phase 6</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
