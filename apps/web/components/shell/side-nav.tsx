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
      className="flex h-screen w-[260px] shrink-0 flex-col overflow-y-auto border-r border-border bg-white px-4 py-6"
    >
      <Link href="/" className="mb-8 block px-2 font-mono text-xs uppercase tracking-[0.15em] text-clinova-deep">
        {productName}
      </Link>

      {NAV_GROUPS.filter((g) => !g.hidden).map((group) => (
        <div key={group.label} className="mb-6">
          <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wider text-neutral">
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
                        <span className="flex cursor-not-allowed items-center justify-between rounded-md px-2 py-1.5 text-sm text-neutral/50">
                          {item.label}
                          <span className="text-[10px] uppercase tracking-wide">Later</span>
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
                      "block rounded-md border-l-2 px-2 py-1.5 text-sm transition-colors",
                      isActive
                        ? "border-clinova-blue bg-secondary font-medium text-clinova-deep"
                        : "border-transparent text-neutral hover:bg-secondary hover:text-clinova-deep",
                    )}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
