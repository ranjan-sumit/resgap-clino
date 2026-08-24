import type { ReactNode } from "react";

// A dark gradient header band, carried from the Landing page's hero energy
// into every inner screen -- the fix for "premium landing page, then a
// flat white admin panel the second you click in."
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
    <div className="relative overflow-hidden rounded-xl bg-hero-gradient px-8 py-8 text-white shadow-raised">
      <div className="pointer-events-none absolute inset-0 bg-brand-glow opacity-70" aria-hidden />
      <div className="relative flex items-start justify-between gap-6">
        <div>
          {eyebrow && (
            <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.18em] text-clinova-cyan">{eyebrow}</p>
          )}
          <h1 className="font-display text-3xl leading-tight text-white">{title}</h1>
          {description && <div className="mt-2 max-w-2xl text-sm text-white/70">{description}</div>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
