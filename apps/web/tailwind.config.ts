import type { Config } from "tailwindcss";
import theme from "../../packages/branding/theme.json";

const c = theme.colors;

// Every derived tone below is computed FROM the branding source at build
// time -- never a new hex literal invented outside packages/branding
// (AD-3/NFR-1). This is what lets the app shell go genuinely dark
// (a real "engineering instrument" sidebar, not a flat white admin panel)
// without smuggling in an arbitrary color nobody chose.
function darken(hex: string, amount: number): string {
  const n = parseInt(hex.replace("#", ""), 16);
  const r = Math.max(0, (n >> 16) - amount);
  const g = Math.max(0, ((n >> 8) & 0xff) - amount);
  const b = Math.max(0, (n & 0xff) - amount);
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}
function mix(hexA: string, hexB: string, t: number): string {
  const a = parseInt(hexA.replace("#", ""), 16);
  const b = parseInt(hexB.replace("#", ""), 16);
  const lerp = (x: number, y: number) => Math.round(x + (y - x) * t);
  const r = lerp((a >> 16) & 0xff, (b >> 16) & 0xff);
  const g = lerp((a >> 8) & 0xff, (b >> 8) & 0xff);
  const bl = lerp(a & 0xff, b & 0xff);
  return `#${((1 << 24) + (r << 16) + (g << 8) + bl).toString(16).slice(1)}`;
}

const sidebarBg = darken(c.clinova_deep_blue, 24); // near-black navy -- a real "control room" chrome
const sidebarBgDeep = darken(c.clinova_deep_blue, 34);
const surface = mix(c.clinova_light_blue, c.white, 0.93); // faint blue-gray content backdrop cards sit on

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand -- sourced from packages/branding/theme.json (AD-3, NFR-1).
        // Never hardcode a hex literal anywhere else in apps/web.
        clinova: {
          blue: c.clinova_blue, // #0093D0 -- primary actions, links (large/bold text only, see contrast note below)
          deep: c.clinova_deep_blue, // #002596 -- headlines, active nav, default link color (~13:1 on white)
          light: c.clinova_light_blue, // #75D1E0 -- accents, chart secondary series
          cyan: c.clinova_cyan, // #00AEEF -- interactive highlights, glow accents
        },
        // Semantic ONLY -- never used decoratively (02-ux-specification.md
        // §3). Enforced by convention: these classes must only appear in
        // components/data/status-badge.tsx and metric-delta.tsx.
        semantic: {
          success: c.success,
          warning: c.warning,
          critical: c.critical,
        },
        // Dark app-chrome tones, derived (not invented) from clinova_deep_blue.
        sidebar: { DEFAULT: sidebarBg, deep: sidebarBgDeep, foreground: c.white },
        surface,
        // shadcn/ui token names, mapped onto the brand palette so every
        // generated primitive is on-brand by default (components.json's
        // cssVariables is false -- these Tailwind classes ARE the theme).
        border: "#E3E7EA",
        input: "#E3E7EA",
        ring: c.clinova_cyan,
        background: c.white,
        foreground: c.clinova_deep_blue,
        primary: { DEFAULT: c.clinova_deep_blue, foreground: c.white },
        secondary: { DEFAULT: "#F4F7F9", foreground: c.clinova_deep_blue },
        muted: { DEFAULT: "#F4F7F9", foreground: c.neutral_gray },
        accent: { DEFAULT: c.clinova_light_blue, foreground: c.clinova_deep_blue },
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
        "sidebar-gradient": `linear-gradient(175deg, ${sidebarBgDeep} 0%, ${sidebarBg} 55%, ${c.clinova_deep_blue} 140%)`,
        "hero-gradient": `linear-gradient(135deg, ${c.clinova_deep_blue} 0%, ${darken(c.clinova_deep_blue, 10)} 60%, ${sidebarBgDeep} 100%)`,
        "accent-line": `linear-gradient(90deg, ${c.clinova_cyan} 0%, ${c.clinova_light_blue} 100%)`,
      },
      fontFamily: {
        display: ["var(--font-display)", "serif"], // DM Serif Display -- page titles, stat numbers
        sans: ["var(--font-body)", "sans-serif"], // DM Sans -- default body text
        mono: ["var(--font-mono)", "monospace"], // DM Mono -- ids, hashes, versions
      },
      borderRadius: { lg: "12px", md: "10px", sm: "7px" },
      boxShadow: {
        // A real elevation scale -- layered, soft shadows instead of a
        // single flat 1px ring, so cards genuinely lift off the surface.
        card: "0 1px 1px rgba(0,37,150,0.03), 0 6px 20px -6px rgba(0,37,150,0.12)",
        "card-hover": "0 2px 4px rgba(0,37,150,0.05), 0 20px 40px -12px rgba(0,37,150,0.22)",
        raised: "0 8px 30px -8px rgba(0,37,150,0.18), 0 2px 6px rgba(0,37,150,0.08)",
        glow: "0 0 0 1px rgba(0,174,239,0.35), 0 0 32px rgba(0,174,239,0.22)",
        "glow-sm": "0 0 0 1px rgba(0,174,239,0.3), 0 0 14px rgba(0,174,239,0.18)",
        "sidebar-line": "1px 0 0 rgba(255,255,255,0.06)",
      },
      spacing: { section: "3rem" },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
