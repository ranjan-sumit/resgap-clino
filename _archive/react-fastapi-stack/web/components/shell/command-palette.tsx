"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CornerDownLeft, FileText, GitBranch, LayoutGrid, Lightbulb, Loader2, Search, SearchX, Waypoints,
} from "lucide-react";
import { Kbd } from "@/components/ui/kbd";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { NAV_GROUPS } from "@/components/shell/nav-config";
import { WORKSPACE_TABS, workspaceHref } from "@/components/workspace/tab-config";
import { api, type SearchHit } from "@/lib/api";

// Sidebar entries PLUS the nine workspace tabs. Deriving destinations from
// NAV_GROUPS alone silently dropped all nine the moment Slice 15 turned them
// into tabs -- searching "corpus" or "gaps" in the palette found nothing,
// even though both screens still existed.
const NAV_DESTINATIONS: { label: string; href: string }[] = [
  ...NAV_GROUPS.filter((g) => !g.hidden)
    .flatMap((g) => g.items)
    .filter((item): item is typeof item & { href: string } => item.status === "live" && !!item.href)
    .map((item) => ({ label: item.label, href: item.href })),
  ...WORKSPACE_TABS.map((t) => ({ label: t.label, href: workspaceHref(t.key) })),
];

type Result = {
  kind: "nav" | SearchHit["kind"];
  href: string;
  label: string;
  meta?: string;
  group: string;
};

const KIND_ICON: Record<string, typeof LayoutGrid> = {
  nav: LayoutGrid,
  paper: FileText,
  entity: Waypoints,
  gap: SearchX,
  proposal: Lightbulb,
  run: GitBranch,
};

const GROUP_ORDER = ["Screens", "Papers", "Entities", "Gaps", "Proposals", "Runs"];
const KIND_GROUP: Record<string, string> = {
  nav: "Screens", paper: "Papers", entity: "Entities",
  gap: "Gaps", proposal: "Proposals", run: "Runs",
};

export function CommandPalette({ projectId }: { projectId?: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const router = useRouter();
  const listRef = useRef<HTMLDivElement>(null);

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
    if (!open) {
      setQuery("");
      setHits([]);
    }
  }, [open]);

  // Debounced content search. Nav filtering stays instant and local -- only
  // the real content query goes to the server, so typing never feels laggy
  // for the common "jump to a screen" case.
  useEffect(() => {
    const q = query.trim();
    if (!open || !projectId || q.length < 2) {
      setHits([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const t = setTimeout(() => {
      api
        .search(projectId, q, 20)
        .then((r) => setHits(r.hits))
        .catch(() => setHits([]))
        .finally(() => setLoading(false));
    }, 180);
    return () => clearTimeout(t);
  }, [query, open, projectId]);

  const results: Result[] = useMemo(() => {
    const q = query.trim().toLowerCase();
    const nav = (q ? NAV_DESTINATIONS.filter((d) => d.label.toLowerCase().includes(q)) : NAV_DESTINATIONS)
      .map((d): Result => ({ kind: "nav", href: d.href, label: d.label, group: "Screens" }));
    const content = hits.map((h): Result => ({
      kind: h.kind,
      href: h.href,
      label: h.title,
      meta: h.subtitle ?? undefined,
      group: KIND_GROUP[h.kind] ?? "Results",
    }));
    return [...nav, ...content];
  }, [query, hits]);

  const grouped = useMemo(() => {
    const byGroup = new Map<string, Result[]>();
    for (const r of results) {
      if (!byGroup.has(r.group)) byGroup.set(r.group, []);
      byGroup.get(r.group)!.push(r);
    }
    return [...byGroup.entries()].sort(
      (a, b) => GROUP_ORDER.indexOf(a[0]) - GROUP_ORDER.indexOf(b[0]),
    );
  }, [results]);

  // Flattened in the same order the groups render, so arrow keys walk the
  // list exactly as it appears rather than in the unsorted source order.
  const flat = useMemo(() => grouped.flatMap(([, items]) => items), [grouped]);

  useEffect(() => setActiveIndex(0), [query, open, hits]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && flat[activeIndex]) {
      e.preventDefault();
      go(flat[activeIndex].href);
    }
  };

  let cursor = -1;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex h-8 w-56 items-center gap-2 rounded-lg border border-border/70 bg-secondary/60 px-2.5 text-xs text-neutral/70 outline-none transition-colors hover:border-clinova-cyan/50 hover:text-clinova-deep focus-visible:ring-2 focus-visible:ring-clinova-cyan/50 focus-visible:ring-offset-1"
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
        <span>Search</span>
        <Kbd className="ml-auto">⌘K</Kbd>
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="top" className="mx-auto max-w-xl rounded-b-xl border-x border-border/60 p-0 shadow-raised">
          <SheetTitle className="sr-only">Search</SheetTitle>
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
            {loading ? (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-neutral" aria-hidden />
            ) : (
              <Search className="h-4 w-4 shrink-0 text-neutral" aria-hidden />
            )}
            <Input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="Search screens, papers, entities, gaps, proposals, runs…"
              className="border-0 shadow-none focus-visible:ring-0"
            />
          </div>

          <div ref={listRef} className="max-h-[60vh] overflow-y-auto p-2">
            {flat.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-neutral">
                {query.trim().length < 2
                  ? "Type at least 2 characters to search content."
                  : loading
                    ? "Searching…"
                    : `No matches for "${query}".`}
              </p>
            ) : (
              grouped.map(([group, items]) => (
                <div key={group} className="mb-1">
                  <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-neutral/70">
                    {group}
                  </p>
                  {items.map((r) => {
                    cursor += 1;
                    const i = cursor;
                    const Icon = KIND_ICON[r.kind] ?? LayoutGrid;
                    return (
                      <button
                        key={`${r.kind}-${r.href}-${r.label}`}
                        onMouseEnter={() => setActiveIndex(i)}
                        onClick={() => go(r.href)}
                        className={cn(
                          "flex w-full items-center justify-between gap-2.5 rounded-md px-2 py-2 text-left text-sm transition-colors",
                          i === activeIndex ? "bg-secondary text-clinova-deep" : "text-clinova-deep",
                        )}
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          <Icon className="h-3.5 w-3.5 shrink-0 text-neutral" aria-hidden />
                          <span className="truncate">{r.label}</span>
                        </span>
                        {r.meta && (
                          <span className="shrink-0 text-xs text-neutral">{r.meta}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
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
