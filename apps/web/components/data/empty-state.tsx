import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";

// 02-ux-specification.md §7: "every list/table screen has a designed
// empty state with a clear next action... not a blank table."
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: { label: string; href: string };
}) {
  return (
    <div className="relative flex flex-col items-center gap-3 overflow-hidden rounded-xl border border-dashed border-clinova-light/40 bg-white px-10 py-16 text-center shadow-card">
      <div className="pointer-events-none absolute inset-0 bg-brand-glow opacity-30" aria-hidden />
      <div className="relative flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-clinova-cyan/15 to-clinova-deep/10">
        <Icon aria-hidden className="h-6 w-6 text-clinova-blue" />
      </div>
      <p className="relative font-display text-xl text-clinova-deep">{title}</p>
      <p className="relative max-w-md text-sm text-neutral">{description}</p>
      {action && (
        <Button asChild variant="outline" className="relative mt-2">
          <Link href={action.href}>{action.label}</Link>
        </Button>
      )}
    </div>
  );
}
