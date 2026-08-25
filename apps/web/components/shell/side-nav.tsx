"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { NAV_GROUPS } from "@/components/shell/nav-config";

export function SideNav({ productName }: { productName: string }) {
  const pathname = usePathname();

  // Longest-prefix match across every live href, so a nested route (e.g.
  // /runs/compare) never lights up its parent (/runs) at the same time.
  const activeHref = NAV_GROUPS.flatMap((g) => g.items)
    .filter((item): item is typeof item & { href: string } => item.status === "live" && !!item.href)
    .map((item) => item.href)
    .filter((href) => pathname === href || pathname?.startsWith(`${href}/`))
    .sort((a, b) => b.length - a.length)[0];

  return (
    <nav
      aria-label="Primary"
      className="relative flex h-screen w-[268px] shrink-0 flex-col overflow-y-auto bg-sidebar-gradient px-4 py-6 text-white shadow-sidebar-line"
    >
      <div className="pointer-events-none absolute inset-0 bg-brand-glow opacity-60" aria-hidden />

      <Link href="/dashboard" className="relative z-10 mb-10 flex items-center gap-2.5 px-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-clinova-cyan to-clinova-light shadow-glow-sm">
          <span className="font-display text-sm text-clinova-deep">C</span>
        </span>
        <span className="font-mono text-[11px] uppercase leading-tight tracking-[0.18em] text-white/90">
          {productName}
        </span>
      </Link>

      <div className="relative z-10">
        {NAV_GROUPS.filter((g) => !g.hidden).map((group) => (
          <div key={group.label} className="mb-6">
            <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/40">
              {group.label}
            </div>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = item.href === activeHref;
                if (item.status === "planned") {
                  return (
                    <li key={item.label}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="flex cursor-not-allowed items-center justify-between rounded-md px-2.5 py-1.5 text-sm text-white/30">
                            {item.label}
                            <span className="text-[9px] uppercase tracking-wide text-white/25">Later</span>
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
                      className={cn(
                        "relative block rounded-md px-2.5 py-1.5 text-sm transition-colors",
                        isActive
                          ? "bg-white/10 font-medium text-white shadow-glow-sm"
                          : "text-white/65 hover:bg-white/5 hover:text-white",
                      )}
                    >
                      {isActive && (
                        <span className="absolute -left-4 top-1/2 h-4 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-clinova-cyan to-clinova-light" />
                      )}
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div className="relative z-10 mt-auto pt-6">
        <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-3">
          <p className="text-[10px] uppercase tracking-wide text-white/40">Workspace</p>
          <p className="mt-1 font-mono text-xs text-white/70">local · phase 5</p>
        </div>
      </div>
    </nav>
  );
}
