"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { NAV_GROUPS } from "@/components/shell/nav-config";
import { RunHistory } from "@/components/shell/run-history";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import type { RunOption } from "@/lib/api";

export function SideNav({
  wordmark,
  descriptor,
  runs = [],
}: {
  wordmark: string;
  descriptor: string;
  runs?: RunOption[];
}) {
  const pathname = usePathname();

  // Longest-prefix match across every live href, so a nested route (e.g.
  // /runs/compare) never lights up its parent (/runs) at the same time.
  const activeHref = NAV_GROUPS.flatMap((g) => g.items)
    .filter((item): item is typeof item & { href: string } => item.status === "live" && !!item.href)
    .map((item) => item.href)
    .filter((href) => pathname === href || pathname?.startsWith(`${href}/`))
    .sort((a, b) => b.length - a.length)[0];

  return (
    // `sticky top-0`, not a plain `h-screen`: the shell is a flex row, so a
    // non-sticky sidebar scrolls up out of view on any page taller than the
    // viewport (Paper Detail, Knowledge Graph), leaving a bare white column
    // where the nav should be. Sticky pins it while <main> scrolls past.
    <nav
      aria-label="Primary"
      className="dark-scroll sticky top-0 z-20 flex h-screen w-[268px] shrink-0 flex-col overflow-y-auto border-r border-chrome-border bg-chrome px-4 py-6"
    >
      <Link href="/workspace" className="mb-8 flex items-center gap-2.5 px-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-clinova-blue">
          <span className="text-sm font-semibold text-white">C</span>
        </span>
        <span className="leading-tight">
          <span className="block text-[15px] font-semibold tracking-tight text-white">{wordmark}</span>
          <span className="block text-[10px] font-medium text-chrome-muted">{descriptor}</span>
        </span>
      </Link>

      <div>
        {NAV_GROUPS.filter((g) => !g.hidden).map((group) => (
          <div key={group.label} className="mb-6">
            <div className="mb-2 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-chrome-muted/70">
              {group.label}
            </div>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = item.href === activeHref;
                const Icon = item.icon;
                if (item.status === "planned") {
                  return (
                    <li key={item.label}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="flex cursor-not-allowed items-center justify-between rounded-md px-2.5 py-1.5 text-sm text-chrome-muted/40">
                            {item.label}
                            <span className="text-[9px] uppercase tracking-wide text-chrome-muted/30">Later</span>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>Not built in this slice yet.</TooltipContent>
                      </Tooltip>
                    </li>
                  );
                }
                return (
                  <li key={item.label}>
                    <Link
                      href={item.href!}
                      aria-current={isActive ? "page" : undefined}
                      className={cn(
                        "relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-all duration-150",
                        isActive
                          ? "bg-white/[0.07] font-medium text-white"
                          : "text-chrome-muted hover:bg-white/[0.04] hover:text-chrome-text",
                      )}
                    >
                      {isActive && (
                        <span className="absolute -left-4 top-1/2 h-4 w-1 -translate-y-1/2 rounded-r-full bg-clinova-cyan" />
                      )}
                      {Icon && <Icon aria-hidden className={cn("h-4 w-4 shrink-0", isActive ? "opacity-100" : "opacity-70")} />}
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}

        {/* Below the nav groups, not above: the nav is fixed and short, the
            run list grows. Streamlit put it in exactly this position. */}
        <RunHistory runs={runs} />
      </div>

      <div className="mt-auto space-y-2 pt-6">
        <ThemeToggle className="w-full justify-center" />
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-3">
          <p className="text-[10px] uppercase tracking-wide text-chrome-muted/70">Workspace</p>
          <p className="mt-1 font-mono text-xs text-chrome-text">local · phase 5</p>
        </div>
      </div>
    </nav>
  );
}
