import type { Metadata } from "next";
import Link from "next/link";
import { SearchX } from "lucide-react";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-chrome px-10">
      <div className="flex w-full max-w-md flex-col items-center gap-3 rounded-xl border border-chrome-border bg-white px-10 py-12 text-center shadow-raised">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-clinova-light/10">
          <SearchX aria-hidden className="h-6 w-6 text-clinova-blue" />
        </div>
        <p className="text-xl font-semibold tracking-tight text-clinova-deep">Page not found</p>
        <p className="max-w-lg text-sm text-neutral">
          There&apos;s nothing at this address. Head back to the dashboard or the run registry.
        </p>
        <div className="mt-2 flex items-center gap-2">
          <Button asChild variant="outline">
            <Link href="/dashboard">Dashboard</Link>
          </Button>
          <Button asChild>
            <Link href="/runs">Runs</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
