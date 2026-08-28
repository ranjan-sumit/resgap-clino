"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";

/**
 * The workspace tab bar (Clinova Phase 5, Slice 15).
 *
 * Deliberately links rather than holding client state: each tab is a real
 * URL, so a tab is bookmarkable, the back button works, and every panel
 * stays a Server Component that fetches on the server. A client-state
 * tab set would have forced all nine panels to render eagerly on every
 * visit -- nine API round-trips to show one.
 */
export interface WorkspaceTab {
  key: string;
  label: string;
}

export function WorkspaceTabs({ tabs, active }: { tabs: WorkspaceTab[]; active: string }) {
  const pathname = usePathname();
  const params = useSearchParams();

  const href = (key: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", key);
    return `${pathname}?${next.toString()}`;
  };

  return (
    <div
      role="tablist"
      aria-label="Workspace sections"
      className="-mb-px flex gap-1 overflow-x-auto border-b border-border"
    >
      {tabs.map((t) => {
        const isActive = t.key === active;
        return (
          <Link
            key={t.key}
            href={href(t.key)}
            role="tab"
            aria-selected={isActive}
            scroll={false}
            className={cn(
              "whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm transition-colors",
              isActive
                ? "border-clinova-cyan font-medium text-clinova-deep"
                : "border-transparent text-neutral hover:border-border hover:text-clinova-deep",
            )}
          >
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
