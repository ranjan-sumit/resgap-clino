import type { Config } from "tailwindcss";
import theme from "../../packages/branding/theme.json";

const c = theme.colors;

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
          cyan: c.clinova_cyan, // #00AEEF -- interactive highlights
        },
        // Semantic ONLY -- never used decoratively (02-ux-specification.md
        // §3). Enforced by convention: these classes must only appear in
        // components/data/status-badge.tsx and metric-delta.tsx.
        semantic: {
          success: c.success,
          warning: c.warning,
          critical: c.critical,
        },
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
      fontFamily: {
        display: ["var(--font-display)", "serif"], // DM Serif Display -- page titles, stat numbers
        sans: ["var(--font-body)", "sans-serif"], // DM Sans -- default body text
        mono: ["var(--font-mono)", "monospace"], // DM Mono -- ids, hashes, versions
      },
      borderRadius: { lg: "10px", md: "8px", sm: "6px" },
      boxShadow: {
        // One flat elevation only -- no stacked/blurred drop shadows
        // (part of avoiding the "generic admin dashboard" look).
        card: "0 1px 2px rgba(0, 37, 150, 0.06), 0 0 0 1px rgba(0, 37, 150, 0.06)",
      },
      spacing: { section: "3rem" },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
