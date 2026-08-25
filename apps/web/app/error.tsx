"use client";

import { useEffect } from "react";
import { AlertOctagon } from "lucide-react";
import { Button } from "@/components/ui/button";

// Root-level fallback (Landing page and anything outside the workspace
// shell) -- the workspace routes have their own error.tsx that keeps the
// sidebar visible; this one has no shell to preserve.
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-surface px-10 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-semantic-critical/[0.08]">
        <AlertOctagon aria-hidden className="h-6 w-6 text-semantic-critical" />
      </div>
      <p className="font-display text-xl text-clinova-deep">Something went wrong</p>
      <p className="max-w-lg text-sm text-neutral">{error.message || "An unexpected error occurred."}</p>
      <Button variant="outline" className="mt-2" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
