import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// A calm, light page header -- eyebrow + title + description, generous
// space, one thin bottom border. Deliberately NOT a dark gradient banner:
// that pattern (tried first) repeated on every single page read as heavy
// and monotonous rather than premium -- a page header should orient the
// reader, not compete with the content below it for attention.
//
// `icon` gives the header a quiet identity: one tinted brand well, the
// same treatment the stat cards use, so every screen reads as the same
// product. `whisper` renders an almost-invisible cyan radial behind the
// header on list pages -- depth without decoration.
export function PageHero({
  eyebrow,
  title,
  description,
  actions,
  icon: Icon,
  whisper = true,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: LucideIcon;
  whisper?: boolean;
}) {
  return (
    <div className="relative">
      {whisper && (
        <div
          className="pointer-events-none absolute -top-16 left-1/2 h-[420px] w-[560px] -translate-x-1/2 rounded-full bg-clinova-cyan/[0.06] blur-3xl dark:bg-dark-primary/[0.10]"
          aria-hidden
        />
      )}
      <div className="relative flex items-start justify-between gap-6 border-b border-border/70 pb-5 dark:border-dark-border">
        <div className={cn("min-w-0", Icon && "flex items-center gap-3.5")}>
          {Icon && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-clinova-blue/10 text-clinova-blue dark:bg-dark-primary/10 dark:text-dark-primary">
              <Icon className="h-[18px] w-[18px]" aria-hidden />
            </span>
          )}
          <div className="min-w-0">
            {eyebrow && (
              <p className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-clinova-deep dark:text-dark-muted-foreground">
                <span className="h-px w-4 bg-clinova-cyan dark:bg-dark-primary" aria-hidden />
                {eyebrow}
              </p>
            )}
            <h1 className="text-[22px] font-semibold tracking-tight text-clinova-deep dark:text-dark-foreground">{title}</h1>
            {description && (
              <div className="mt-1.5 max-w-2xl text-sm leading-relaxed text-neutral dark:text-dark-muted-foreground">
                {description}
              </div>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2 pt-1">{actions}</div>}
      </div>
    </div>
  );
}
