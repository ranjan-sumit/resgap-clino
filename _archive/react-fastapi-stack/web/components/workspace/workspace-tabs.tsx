"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * The workspace tab bar (Clinova Phase 5, Slice 15).
 *
 * Deliberately links rather than holding client state: each tab is a real
 * URL, so a tab is bookmarkable, the back button works, and every panel
 * stays a Server Component that fetches on the server. A client-state
 * tab set would have forced all nine panels to render eagerly on every
 * visit -- nine API round-trips to show one.
 *
 * Visual pass (2026-09-08, reported as "looks bad" against run-detail's
 * segmented-pill tabs): with 9 tabs, a pill/chip style gets cramped --
 * underline tabs are the right structural choice here, they were just
 * under-styled (bare text + a flat border, no hover surface, no active
 * motion). The active underline now slides between tabs via a shared
 * Framer Motion layoutId instead of snapping, and each tab gets a real
 * hover surface matching the rest of the app's interactive-chrome language.
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
      className="dark-scroll sticky top-14 z-10 -mb-px flex gap-0.5 overflow-x-auto border-b border-border bg-surface pb-px dark:border-dark-border dark:bg-dark-background"
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
              "relative whitespace-nowrap rounded-t-md px-3.5 py-2.5 text-sm transition-colors",
              isActive
                ? "font-medium text-clinova-deep dark:text-dark-foreground"
                : "text-neutral hover:bg-secondary/60 hover:text-clinova-deep dark:text-dark-muted-foreground dark:hover:bg-dark-secondary/60 dark:hover:text-dark-foreground",
            )}
          >
            {t.label}
            {isActive && (
              <motion.span
                layoutId="workspace-tab-indicator"
                className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-clinova-cyan dark:bg-dark-primary"
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
              />
            )}
          </Link>
        );
      })}
    </div>
  );
}
