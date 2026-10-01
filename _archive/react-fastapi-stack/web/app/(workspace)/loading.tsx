import { Skeleton } from "@/components/ui/skeleton";

// Instant feedback while a workspace page's server components fetch (the
// dashboard alone can take seconds against a real registry). Without this
// Next suspends on a blank white <main> -- the app looked broken on every
// navigation. The skeleton mirrors PageHero + card sections so the layout
// does not jump when real content streams in.
export default function WorkspaceLoading() {
  return (
    <div className="mx-auto max-w-6xl space-y-8 animate-fade-up" aria-busy="true" aria-label="Loading page">
      <div className="space-y-2 border-b border-border/70 pb-6">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>

      <div className="space-y-3">
        <Skeleton className="h-3 w-36" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <Skeleton className="h-3 w-28" />
        <div className="grid grid-cols-2 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
      </div>
    </div>
  );
}
