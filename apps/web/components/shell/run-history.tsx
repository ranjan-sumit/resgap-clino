"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import type { RunOption } from "@/lib/api";

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
 * Selecting a run here keeps the current tab and only changes ?run=.
 */
export function RunHistory({ runs }: { runs: RunOption[] }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const selected = params.get("run");

  if (runs.length === 0) return null;

  // Only the workspace is run-scoped; from anywhere else, picking a run
  // should land you in the workspace rather than silently appending a
  // ?run= that page ignores.
  const base = pathname === "/workspace" ? "/workspace" : "/workspace";

  const href = (runId: string) => {
    const next = new URLSearchParams(pathname === "/workspace" ? params.toString() : "");
    next.set("run", runId);
    return `${base}?${next.toString()}`;
  };

  return (
    <div className="mb-6">
      <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/40">
        Run history
      </div>
      <ul className="space-y-0.5">
        {runs.map((r, i) => {
          // No ?run= means the workspace is showing the newest run, so the
          // first row is the live one -- highlighting nothing would be wrong.
          const isActive = selected ? selected === r.run_id : i === 0;
          return (
            <li key={r.run_id}>
              <Link
                href={href(r.run_id)}
                className={cn(
                  "block rounded-md px-2.5 py-1.5 transition-colors",
                  isActive ? "bg-white/10 text-white" : "text-white/65 hover:bg-white/5 hover:text-white",
                )}
              >
                <span className="block truncate text-[13px]">{r.name}</span>
                <span className="mt-0.5 block font-mono text-[10px] text-white/40">
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
