import type { ReactNode } from "react";

// A calm, light page header -- eyebrow + title + description, generous
// space, one thin bottom border. Deliberately NOT a dark gradient banner:
// that pattern (tried first) repeated on every single page read as heavy
// and monotonous rather than premium -- a page header should orient the
// reader, not compete with the content below it for attention.
export function PageHero({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-border/70 pb-6">
      <div>
        {eyebrow && (
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-[0.18em] text-clinova-deep">{eyebrow}</p>
        )}
        <h1 className="font-display text-[28px] leading-tight text-clinova-deep">{title}</h1>
        {description && <div className="mt-1.5 max-w-2xl text-sm text-neutral">{description}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
