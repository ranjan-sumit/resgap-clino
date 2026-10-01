import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { HeroVisual } from "@/components/landing/hero-visual";
import { getBranding } from "@/lib/branding";

export default async function LandingPage() {
  const { theme, copy } = await getBranding();
  const { landing } = copy;

  return (
    <main className="min-h-screen">
      {/* Dark graphite hero -- the one deliberate brand moment. The cyan
         radial glow lives here and only here; inside the app the chrome is
         flat and quiet. */}
      <section className="relative grid min-h-screen grid-cols-[minmax(0,7fr)_minmax(0,6fr)] bg-chrome text-chrome-text">
        <div className="pointer-events-none absolute inset-0 bg-brand-glow opacity-70" aria-hidden />

        <div className="relative flex flex-col justify-center px-16 py-20">
          <div className="mb-8 inline-flex w-fit items-center gap-2.5 rounded-full border border-white/10 bg-white/5 py-1 pl-1 pr-3">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-clinova-blue">
              <span className="text-[10px] font-semibold text-white">C</span>
            </span>
            <span className="text-[13px] font-semibold tracking-tight text-white">{theme.product_wordmark}</span>
            <span className="text-[11px] font-medium text-chrome-muted">{theme.product_descriptor}</span>
            <span className="relative flex h-1.5 w-1.5" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-clinova-cyan opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-clinova-cyan" />
            </span>
          </div>

          <p className="mb-5 text-sm font-medium uppercase tracking-[0.2em] text-chrome-muted">
            {theme.tagline}
          </p>
          <h1 className="mb-6 max-w-[16ch] font-display text-6xl leading-[1.05] tracking-tight text-white">
            {landing.hero_headline}
          </h1>
          <p className="mb-10 max-w-[52ch] text-lg leading-relaxed text-chrome-muted">
            {landing.hero_supporting}
          </p>
          <div className="flex items-center gap-4">
            <Button asChild size="lg" className="px-6">
              <Link href="/dashboard">
                {landing.primary_cta}
                <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline" className="border-white/20 bg-transparent px-6 text-chrome-text hover:bg-white/10 hover:text-white">
              <Link href="/runs">{landing.secondary_cta}</Link>
            </Button>
          </div>
        </div>

        <div className="relative hidden md:block">
          <HeroVisual />
        </div>
      </section>

      {/* Trust strip flips back to white: the dark hero is the brand
         moment, the content below stays clinical and bright. */}
      <section className="flex items-center justify-between gap-6 border-t border-border bg-white px-16 py-6">
        <div className="flex items-center gap-6 text-xs uppercase tracking-wider text-neutral">
          {landing.footer_trust_strip.map((item: string, i: number) => (
            <span key={item} className="flex items-center gap-6">
              {i > 0 && <span className="h-3 w-px bg-border" aria-hidden />}
              <span className="flex items-center gap-1.5">
                <CheckCircle2 aria-hidden className="h-3.5 w-3.5 text-semantic-success" />
                {item}
              </span>
            </span>
          ))}
        </div>
        {/* The full legal product_name lives here (and in Settings), not in
           the hero -- the hero carries the wordmark lockup instead. */}
        <p className="text-xs text-neutral/60">{theme.product_name}</p>
      </section>
    </main>
  );
}
