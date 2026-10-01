"use client";

import { statIcon } from "@/components/data/stat-icons";
import { StaggerItem, StaggerList } from "@/components/motion/stagger-list";
import { CountUp } from "@/components/motion/count-up";
import type { CountStat } from "@/lib/api";

/**
 * Workspace header stat strip -- one compact row, real cards instead of
 * bare divided text columns. Reported as "looks like some html frontend,
 * not enterprise" (2026-09-09): the previous version was a single flat
 * `divide-x` row of plain numbers with no icon, no color, no depth, no
 * motion -- functionally fine, visually indistinguishable from an
 * unstyled table. Deliberately still ONE row, not a full CountStatView
 * grid: the original "dense strip, not eight cards" reasoning (fitting
 * the tab bar above the fold on a 1440x900 screen) still holds -- this
 * keeps that density while giving each tile the same icon-well/hover/
 * shadow language every other card in the app already uses, plus a real
 * count-up reveal on first paint instead of numbers just appearing.
 */
export function WorkspaceStatStrip({ counts }: { counts: CountStat[] }) {
  return (
    <StaggerList className="flex flex-wrap gap-2.5">
      {counts.map((c) => {
        const Icon = statIcon(c.key);
        const numeric = typeof c.value === "number" ? c.value : null;
        return (
          <StaggerItem key={c.key} className="flex-1 basis-[140px]">
            <div
              title={c.source}
              className="group relative flex items-center gap-3 overflow-hidden rounded-lg border border-border/60 bg-card px-3.5 py-2.5 shadow-card transition-all duration-200 hover:-translate-y-px hover:shadow-card-hover dark:border-dark-border dark:bg-dark-card"
            >
              <div className="pointer-events-none absolute inset-x-0 top-0 h-[2px] bg-accent-line opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-clinova-blue/10 text-clinova-blue dark:bg-dark-primary/10 dark:text-dark-primary">
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="text-lg font-semibold leading-tight tracking-tight tabular-nums text-clinova-deep dark:text-dark-foreground">
                  {numeric !== null ? <CountUp value={numeric} /> : c.display}
                </p>
                <p className="truncate text-[10px] font-medium uppercase tracking-wide text-neutral dark:text-dark-muted-foreground">
                  {c.label}
                </p>
              </div>
            </div>
          </StaggerItem>
        );
      })}
    </StaggerList>
  );
}
