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
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-secondary/40 px-10 py-16 text-center">
      <Icon aria-hidden className="h-8 w-8 text-clinova-light" />
      <p className="font-display text-xl text-clinova-deep">{title}</p>
      <p className="max-w-md text-sm text-neutral">{description}</p>
      {action && (
        <Button asChild variant="outline" className="mt-2">
          <Link href={action.href}>{action.label}</Link>
        </Button>
      )}
    </div>
  );
}
