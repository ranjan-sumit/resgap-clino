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
  secondaryAction,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: { label: string; href: string };
  secondaryAction?: { label: string; href: string };
}) {
  return (
    <div className="flex flex-col items-center gap-3 overflow-hidden rounded-xl border border-dashed border-clinova-light/40 bg-white px-10 py-16 text-center shadow-card">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-clinova-cyan/10">
        <Icon aria-hidden className="h-5 w-5 text-clinova-blue" />
      </div>
      <p className="text-sm font-semibold text-clinova-deep">{title}</p>
      <p className="max-w-sm text-sm leading-relaxed text-neutral">{description}</p>
      {(action || secondaryAction) && (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {action && (
            <Button asChild>
              <Link href={action.href}>{action.label}</Link>
            </Button>
          )}
          {secondaryAction && (
            <Button asChild variant="outline">
              <Link href={secondaryAction.href}>{secondaryAction.label}</Link>
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
