"use client";

import { useEffect } from "react";
import { AlertOctagon } from "lucide-react";
import { Button } from "@/components/ui/button";

// Keeps the sidebar/top bar mounted (this file sits inside the workspace
// layout, not at the root) so a page-level error doesn't blank the whole
// screen -- the nav stays usable, only the content area shows the failure.
// Never a generic "Something went wrong": the real error message is always
// shown, matching ErrorState's own "names what failed and why" rule.
export default function WorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col items-center gap-3 rounded-xl border border-semantic-critical/20 bg-white px-10 py-16 text-center shadow-card">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-semantic-critical/[0.08]">
        <AlertOctagon aria-hidden className="h-6 w-6 text-semantic-critical" />
      </div>
      <p className="font-display text-xl text-clinova-deep">This screen hit an error</p>
      <p className="max-w-lg text-sm text-neutral">{error.message || "An unexpected error occurred."}</p>
      {error.digest && <p className="font-mono text-xs text-neutral/60">Digest: {error.digest}</p>}
      <Button variant="outline" className="mt-2" onClick={reset}>
        Try again
      </Button>
    </div>
  );
}
