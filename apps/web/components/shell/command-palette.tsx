"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CornerDownLeft, FileSearch2, LayoutGrid, Search } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { NAV_GROUPS } from "@/components/shell/nav-config";
import { api, type RunSummary } from "@/lib/api";

const NAV_DESTINATIONS = NAV_GROUPS.filter((g) => !g.hidden)
  .flatMap((g) => g.items)
  .filter((item): item is typeof item & { href: string } => item.status === "live" && !!item.href);

type Result = { kind: "nav" | "run"; href: string; label: string; meta?: string };

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const router = useRouter();

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (open && runs === null) {
      api.listRuns(50).then((r) => setRuns(r.runs)).catch(() => setRuns([]));
    }
    if (!open) setQuery("");
  }, [open, runs]);

  const results: Result[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    const nav = (q ? NAV_DESTINATIONS.filter((d) => d.label.toLowerCase().includes(q)) : NAV_DESTINATIONS).map(
      (d): Result => ({ kind: "nav", href: d.href, label: d.label }),
    );
    const runList = runs ?? [];
    const matchedRuns = (
      q ? runList.filter((r) => r.name.toLowerCase().includes(q) || r.run_id.includes(q)) : runList.slice(0, 6)
    )
      .slice(0, 8)
      .map((r): Result => ({ kind: "run", href: `/runs/${r.run_id}`, label: r.name, meta: r.run_id.slice(0, 8) }));
    return [...nav, ...matchedRuns];
  }, [query, runs]);

  useEffect(() => setActiveIndex(0), [query, open]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results[activeIndex]) {
      e.preventDefault();
      go(results[activeIndex].href);
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex h-8 items-center gap-1.5 rounded-md border border-border/70 px-2.5 text-xs text-neutral transition-colors hover:border-clinova-blue/40 hover:text-clinova-deep"
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden sm:inline">Search</span>
        <kbd className="ml-1 rounded border border-border bg-muted px-1 font-mono text-[10px]">⌘K</kbd>
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="top" className="mx-auto max-w-xl rounded-b-xl border-x border-border/60 p-0 shadow-raised">
          <SheetTitle className="sr-only">Search</SheetTitle>
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
            <Search className="h-4 w-4 shrink-0 text-neutral" aria-hidden />
            <Input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="Jump to a screen or find a run by name or id…"
              className="border-0 shadow-none focus-visible:ring-0"
            />
          </div>
          <div className="max-h-[60vh] overflow-y-auto p-2">
            {results.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-neutral">No matches for &quot;{query}&quot;.</p>
            ) : (
              results.map((r, i) => (
                <button
                  key={`${r.kind}-${r.href}`}
                  onMouseEnter={() => setActiveIndex(i)}
                  onClick={() => go(r.href)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2.5 rounded-md px-2 py-2 text-left text-sm",
                    i === activeIndex ? "bg-secondary text-clinova-deep" : "text-clinova-deep",
                  )}
                >
                  <span className="flex items-center gap-2.5">
                    {r.kind === "nav" ? (
                      <LayoutGrid className="h-3.5 w-3.5 shrink-0 text-neutral" aria-hidden />
                    ) : (
                      <FileSearch2 className="h-3.5 w-3.5 shrink-0 text-neutral" aria-hidden />
                    )}
                    {r.label}
                  </span>
                  {r.meta && <span className="font-mono text-xs text-neutral">{r.meta}</span>}
                </button>
              ))
            )}
          </div>
          <div className="flex items-center justify-end gap-1 border-t border-border/60 px-4 py-2 text-[11px] text-neutral">
            <CornerDownLeft className="h-3 w-3" aria-hidden /> select · Esc to close
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
