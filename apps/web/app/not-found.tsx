import type { Metadata } from "next";
import Link from "next/link";
import { SearchX } from "lucide-react";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-surface px-10 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-clinova-light/10">
        <SearchX aria-hidden className="h-6 w-6 text-clinova-blue" />
      </div>
      <p className="font-display text-xl text-clinova-deep">Page not found</p>
      <p className="max-w-lg text-sm text-neutral">
        There's nothing at this address. Head back to the dashboard or the run registry.
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
  );
}
