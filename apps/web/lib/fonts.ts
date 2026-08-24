import { DM_Mono, DM_Sans, DM_Serif_Display } from "next/font/google";

// packages/branding/theme.json stores CSS font-stack strings
// ("'DM Sans', sans-serif"); next/font needs a loader per family. This
// file is the single mapping point between the two representations --
// tailwind.config.ts's fontFamily.{display,sans,mono} reference these
// exact CSS variable names.
export const fontBody = DM_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  weight: ["400", "500", "700"],
});

export const fontDisplay = DM_Serif_Display({
  subsets: ["latin"],
  variable: "--font-display",
  weight: "400",
});

export const fontMono = DM_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500"],
});
