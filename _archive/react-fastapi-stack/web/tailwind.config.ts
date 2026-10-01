import type { Config } from "tailwindcss";
import { lighten, readableColor, transparentize } from "color2k";
import theme from "../../packages/branding/theme.json";

const c = theme.colors;

// Every derived tone below is computed FROM the branding source at build
// time -- never a new hex literal invented outside packages/branding
// (AD-3/NFR-1). This is what lets the app shell go genuinely dark without
// smuggling in an arbitrary color nobody chose.
function mix(hexA: string, hexB: string, t: number): string {
  const a = parseInt(hexA.replace("#", ""), 16);
  const b = parseInt(hexB.replace("#", ""), 16);
  const lerp = (x: number, y: number) => Math.round(x + (y - x) * t);
  const r = lerp((a >> 16) & 0xff, (b >> 16) & 0xff);
  const g = lerp((a >> 8) & 0xff, (b >> 8) & 0xff);
  const bl = lerp(a & 0xff, b & 0xff);
  return `#${((1 << 24) + (r << 16) + (g << 8) + bl).toString(16).slice(1)}`;
}

const surface = mix(c.clinova_cyan, c.white, 0.95); // faint blue content backdrop cards sit on

// Dark-mode content-page tokens. Not a manual re-guess of a light palette --
// derived from the SAME chrome_bg graphite family the sidebar already uses
// (so dark mode reads as one cohesive dark surface, not two different
// darks), plus color2k's readableColor() to guarantee every foreground/
// background pair below actually passes contrast rather than being
// eyeballed -- this project has already shipped one real contrast bug
// (the original clinova_blue #0093D0 failed WCAG AA and had to be swapped
// for #0000C9), so this is a real bug class here, not a formality.
// A fully separate `dark-*` namespace (not a redefinition of the existing
// light tokens) so dark mode rolls out screen-by-screen via `dark:` variants
// with zero risk to any screen that hasn't opted in yet.
const darkBg = c.chrome_bg_deep; // #08090F -- matches sidebar's darkest tone
const darkCard = lighten(c.chrome_bg, 0.02); // one step up from sidebar bg, for elevation
const darkSecondary = lighten(c.chrome_bg, 0.05);
const darkBorder = c.chrome_border; // reuse sidebar's own border tone, already dark-tuned
const darkForeground = c.chrome_text; // reuse sidebar's own text tone, already dark-tuned
const darkMutedForeground = c.chrome_muted;
const darkPrimary = c.clinova_cyan; // brighter accent -- deep blue would nearly vanish on dark bg

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Dark-mode content-page namespace -- see the derivation comment
        // above. Opt in per-element via `dark:bg-dark-card` etc.; the
        // existing light tokens (`bg-card`, `bg-background`, ...) are
        // completely untouched by this.
        "dark-background": darkBg,
        "dark-card": { DEFAULT: darkCard, foreground: darkForeground },
        "dark-popover": { DEFAULT: darkCard, foreground: darkForeground },
        "dark-secondary": { DEFAULT: darkSecondary, foreground: darkForeground },
        "dark-muted": { DEFAULT: darkSecondary, foreground: darkMutedForeground },
        "dark-accent": { DEFAULT: darkSecondary, foreground: darkForeground },
        "dark-border": darkBorder,
        "dark-input": darkBorder,
        "dark-ring": darkPrimary,
        "dark-foreground": darkForeground,
        "dark-primary": { DEFAULT: darkPrimary, foreground: readableColor(darkPrimary) },
        "dark-destructive": { DEFAULT: c.critical, foreground: readableColor(c.critical) },
        "dark-glow": transparentize(darkPrimary, 0.75), // for pulsing/active states on dark surfaces
        // Brand -- sourced from packages/branding/theme.json (AD-3, NFR-1).
        // Never hardcode a hex literal anywhere else in apps/web.
        clinova: {
          blue: c.clinova_blue, // #0000C9 -- Pfizer blue: primary actions, links (~8.6:1 on white)
          deep: c.clinova_deep_blue, // #0000A0 -- hover/active, headlines, active nav (~10:1 on white)
          light: c.clinova_light_blue, // #85BDFB -- light sky tint: chart secondary series, entity accents
          cyan: c.clinova_cyan, // #3D96F7 -- sky accent: interactive highlights, glow, focus ring
        },
        // Semantic ONLY -- never used decoratively (02-ux-specification.md
        // §3). Enforced by convention: these classes must only appear in
        // components/data/status-badge.tsx and metric-delta.tsx.
        semantic: {
          success: c.success,
          warning: c.warning,
          critical: c.critical,
        },
        // Dark app-chrome tones -- an explicit graphite palette from
        // theme.json. (Earlier revisions "derived" these by darkening
        // clinova_deep_blue, but even subtraction keeps the blue channel
        // saturated, which is exactly how the sidebar ended up loud royal
        // blue. Graphite is a chosen color, not a darkened brand color.)
        sidebar: { DEFAULT: c.chrome_bg, deep: c.chrome_bg_deep, foreground: c.chrome_text, muted: c.chrome_muted },
        chrome: { DEFAULT: c.chrome_bg, deep: c.chrome_bg_deep, border: c.chrome_border, text: c.chrome_text, muted: c.chrome_muted },
        surface,
        // shadcn/ui token names, mapped onto the brand palette so every
        // generated primitive is on-brand by default (components.json's
        // cssVariables is false -- these Tailwind classes ARE the theme).
        border: c.brand_border,
        input: c.brand_border,
        ring: c.clinova_cyan,
        background: c.white,
        foreground: c.clinova_deep_blue,
        primary: { DEFAULT: c.clinova_blue, foreground: c.white },
        secondary: { DEFAULT: c.brand_tint, foreground: c.clinova_deep_blue },
        muted: { DEFAULT: c.brand_tint_deep, foreground: c.neutral_gray },
        accent: { DEFAULT: c.brand_tint, foreground: c.clinova_deep_blue },
        destructive: { DEFAULT: c.critical, foreground: c.white },
        card: { DEFAULT: c.white, foreground: c.neutral_gray },
        popover: { DEFAULT: c.white, foreground: c.neutral_gray },
        // Direct access to the body-text gray (02-ux-specification.md §3)
        // for anywhere the `muted-foreground` shadcn alias doesn't fit.
        neutral: c.neutral_gray,
      },
      backgroundImage: {
        // Composed purely from existing brand tokens -- gradients, not new colors.
        "brand-glow": `radial-gradient(60% 60% at 30% 20%, ${c.clinova_cyan}33 0%, transparent 70%)`,
        "hero-gradient": `linear-gradient(135deg, ${c.chrome_bg_deep} 0%, ${mix(c.chrome_bg, c.clinova_deep_blue, 0.85)} 60%, ${c.chrome_bg} 100%)`,
        "accent-line": `linear-gradient(90deg, ${c.clinova_cyan} 0%, ${c.clinova_light_blue} 100%)`,
      },
      fontFamily: {
        display: ["var(--font-display)", "serif"], // DM Serif Display -- landing hero headline ONLY; in-app headings are sans
        sans: ["var(--font-body)", "sans-serif"], // DM Sans -- default body text
        mono: ["var(--font-mono)", "monospace"], // DM Mono -- ids, hashes, versions
      },
      // One type scale for the whole app, so "title" on one screen can never
      // drift from "title" on another. Sizes pair their tracking: display
      // type tightens, captions widen.
      fontSize: {
        display: ["2.5rem", { lineHeight: "1.1", letterSpacing: "-0.01em" }],
        "3xl": ["1.75rem", { lineHeight: "1.2", letterSpacing: "-0.01em" }],
        "2xl": ["1.5rem", { lineHeight: "1.25", letterSpacing: "-0.005em" }],
        xl: ["1.25rem", { lineHeight: "1.35" }],
        lg: ["1.125rem", { lineHeight: "1.5" }],
        base: ["0.9375rem", { lineHeight: "1.55" }],
        sm: ["0.875rem", { lineHeight: "1.5" }],
        xs: ["0.75rem", { lineHeight: "1.45" }],
        "2xs": ["0.6875rem", { lineHeight: "1.4" }],
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.6s linear infinite",
        "fade-up": "fade-up 250ms ease-out both",
      },
      borderRadius: { lg: "12px", md: "10px", sm: "7px" },
      boxShadow: {
        // A real elevation scale -- layered, soft shadows instead of a
        // single flat 1px ring, so cards genuinely lift off the surface.
        // All tints share the Pfizer navy base rgba(0,0,40,...) so shadows
        // read cool rather than gray.
        card: "0 1px 3px rgba(0,0,40,0.08)",
        "card-hover": "0 2px 4px rgba(0,0,40,0.06), 0 12px 24px -8px rgba(0,0,40,0.18)",
        raised: "0 8px 30px -8px rgba(0,0,40,0.18), 0 2px 6px rgba(0,0,40,0.08)",
        "sidebar-line": "1px 0 0 rgba(255,255,255,0.07)",
      },
      spacing: { section: "3rem" },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
