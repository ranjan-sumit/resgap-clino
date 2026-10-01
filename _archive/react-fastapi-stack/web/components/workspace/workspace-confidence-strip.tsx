"use client";

import { Gauge } from "lucide-react";
import { StaggerItem, StaggerList } from "@/components/motion/stagger-list";

export interface ConfidenceMeasure {
  key: string;
  label: string;
  display: string;
  basis: string;
  recorded: boolean;
}

/**
 * Recorded confidence values as real chips instead of bare inline text.
 * Same "looks like html frontend" fix as workspace-stat-strip.tsx, applied
 * to the row directly below it -- previously five `<span>`s of plain text
 * with no card, no color, no depth. Unmeasured values stay folded into the
 * disclosure (02-ux-specification.md's editorial call, unchanged: absence
 * shouldn't get more visual weight than presence).
 */
export function WorkspaceConfidenceStrip({ measures }: { measures: ConfidenceMeasure[] }) {
  const recorded = measures.filter((m) => m.recorded);
  const unmeasured = measures.filter((m) => !m.recorded);

  if (measures.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <StaggerList className="flex flex-wrap gap-2">
        {recorded.map((m) => (
          <StaggerItem key={m.key}>
            <div
              title={m.basis}
              className="group flex items-center gap-2 rounded-full border border-border/60 bg-card py-1 pl-2 pr-3 shadow-card transition-all duration-200 hover:-translate-y-px hover:shadow-card-hover dark:border-dark-border dark:bg-dark-card"
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-clinova-cyan/10 text-clinova-cyan dark:bg-dark-primary/10 dark:text-dark-primary">
                <Gauge className="h-3 w-3" aria-hidden />
              </span>
              <span className="text-[11px] uppercase tracking-wide text-neutral dark:text-dark-muted-foreground">
                {m.label}
              </span>
              <span className="text-sm font-semibold tracking-tight text-clinova-deep dark:text-dark-foreground">
                {m.display}
              </span>
            </div>
          </StaggerItem>
        ))}
      </StaggerList>

      {unmeasured.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none rounded-full border border-dashed border-border/60 px-3 py-1 text-xs text-neutral underline decoration-dotted underline-offset-4 transition-colors hover:border-border hover:text-clinova-deep dark:border-dark-border dark:text-dark-muted-foreground dark:hover:text-dark-foreground">
            {unmeasured.length} of {measures.length} confidence measures not recorded — why
          </summary>
          <ul className="mt-2 w-full space-y-1.5 rounded-md border border-border/60 bg-card p-3 shadow-card dark:border-dark-border dark:bg-dark-card">
            {unmeasured.map((m) => (
              <li key={m.key} className="text-xs leading-relaxed">
                <span className="font-medium text-neutral dark:text-dark-muted-foreground">{m.label}:</span>{" "}
                <span className="text-neutral dark:text-dark-muted-foreground">{m.basis}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
