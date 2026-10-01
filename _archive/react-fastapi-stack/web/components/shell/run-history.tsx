"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { History } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RunOption } from "@/lib/api";

const RUN_SCOPED_PATHS = ["/workspace", "/dashboard"];
const LIMIT_OPTIONS = [5, 10, 25, 50] as const;

/**
 * Always-visible run history in the sidebar (Clinova Phase 5, Slice 15).
 *
 * Streamlit put every past run one click away, with enough preview to tell
 * them apart (`2026-08-21 14:07 · 2p · 5g`). The React app had no run
 * switcher at all: the top bar's dropdown selects a PROJECT, and with one
 * project in the dataset it looked like a run switcher that did nothing.
 * Switching runs meant navigating to /runs, finding the row, and clicking
 * through -- losing whichever tab you were reading.
 *
 * Selecting a run here keeps the current tab and only changes ?run= -- for
 * both run-scoped screens (Workspace and Dashboard, which both read ?run=
 * server-side). Anywhere else, picking a run lands you in the Workspace
 * rather than silently appending a ?run= that screen ignores.
 */
export function RunHistory({ runs }: { runs: RunOption[] }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const selected = params.get("run");
  // Client-side only: this list is already the cheap, pre-fetched
  // run-options list (see the layout), so narrowing it needs no refetch.
  const [limit, setLimit] = useState<(typeof LIMIT_OPTIONS)[number]>(10);

  if (runs.length === 0) return null;

  const runScoped = RUN_SCOPED_PATHS.includes(pathname ?? "");
  const base = runScoped ? pathname! : "/workspace";

  const href = (runId: string) => {
    const next = new URLSearchParams(runScoped ? params.toString() : "");
    next.set("run", runId);
    return `${base}?${next.toString()}`;
  };

  const visible = runs.slice(0, limit);

  return (
    <div className="mb-6">
      <div className="mb-2 flex items-center justify-between gap-1.5 px-2.5">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-chrome-muted/70">
          <History aria-hidden className="h-3 w-3" />
          Run history
        </div>
        <div className="flex items-center gap-0.5 text-[10px] text-chrome-muted/70">
          {LIMIT_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setLimit(n)}
              className={cn(
                "rounded px-1 tabular-nums",
                n === limit ? "font-semibold text-chrome-text" : "hover:text-chrome-text",
              )}
            >
              {n}
            </button>
          ))}
        </div>
      </div>
      <ul className="space-y-0.5">
        {visible.map((r, i) => {
          // No ?run= means the workspace is showing the newest run, so the
          // first row is the live one -- highlighting nothing would be wrong.
          const isActive = selected ? selected === r.run_id : i === 0;
          return (
            <li key={r.run_id}>
              <Link
                href={href(r.run_id)}
                aria-current={isActive ? "true" : undefined}
                className={cn(
                  "block rounded-md border-l-2 px-2.5 py-1.5 transition-all duration-150",
                  isActive
                    ? "border-clinova-cyan bg-clinova-blue/15 text-white"
                    : "border-transparent text-chrome-muted hover:bg-white/[0.04] hover:text-chrome-text",
                )}
              >
                <span className="block truncate text-[13px]">{r.name}</span>
                <span className="mt-0.5 block font-mono text-[10px] text-chrome-muted/70">
                  {r.created_at.slice(0, 16).replace("T", " ")} · {r.n_papers}p · {r.n_gaps}g
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
