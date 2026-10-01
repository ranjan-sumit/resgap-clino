import Link from "next/link";
import { AlertOctagon } from "lucide-react";
import { Button } from "@/components/ui/button";

// 02-ux-specification.md §7: "a failed stage names what failed and why...
// with a retry action where applicable." The API's own error `detail`
// is what gets rendered here -- e.g. the 503 handler's real
// "start pg_ctl" instruction -- never a generic "Something went wrong."
export function ErrorState({
  title = "Something went wrong",
  detail,
  retryHref,
}: {
  title?: string;
  detail: string;
  retryHref?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-semantic-critical/20 bg-white px-10 py-16 text-center shadow-card">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-semantic-critical/[0.08]">
        <AlertOctagon aria-hidden className="h-6 w-6 text-semantic-critical" />
      </div>
      <p className="text-xl font-semibold tracking-tight text-clinova-deep">{title}</p>
      <p className="max-w-lg text-sm leading-relaxed text-neutral">{detail}</p>
      {retryHref && (
        <Button asChild variant="outline" className="mt-2">
          <Link href={retryHref}>Try again</Link>
        </Button>
      )}
    </div>
  );
}
