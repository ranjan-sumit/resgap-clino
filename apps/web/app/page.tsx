import Link from "next/link";
import { Button } from "@/components/ui/button";
import { HeroVisual } from "@/components/landing/hero-visual";
import { getBranding } from "@/lib/branding";

export default async function LandingPage() {
  const { theme, copy } = await getBranding();
  const { landing } = copy;

  return (
    <main className="grid min-h-screen grid-cols-[minmax(0,7fr)_minmax(0,6fr)]">
      <div className="flex flex-col justify-center px-16 py-20">
        <div className="mb-10 font-mono text-xs uppercase tracking-[0.2em] text-clinova-deep">
          {theme.product_name}
        </div>
        <p className="mb-6 text-sm text-neutral">{theme.tagline}</p>
        <h1 className="mb-6 max-w-[16ch] font-display text-6xl leading-[1.05] text-clinova-deep">
          {landing.hero_headline}
        </h1>
        <p className="mb-10 max-w-[52ch] text-lg leading-relaxed text-neutral">
          {landing.hero_supporting}
        </p>
        <div className="flex items-center gap-4">
          <Button asChild size="lg">
            <Link href="/dashboard">{landing.primary_cta}</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/runs">{landing.secondary_cta}</Link>
          </Button>
        </div>

        <div className="mt-24 flex items-center gap-6 font-mono text-xs uppercase tracking-wider text-neutral">
          {landing.footer_trust_strip.map((item: string, i: number) => (
            <span key={item} className="flex items-center gap-6">
              {i > 0 && <span className="h-3 w-px bg-clinova-light" aria-hidden />}
              {item}
            </span>
          ))}
        </div>
      </div>

      <div className="relative hidden md:block">
        <HeroVisual />
      </div>
    </main>
  );
}
