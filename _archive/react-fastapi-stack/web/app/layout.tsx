import type { Metadata } from "next";
import { fontBody, fontDisplay, fontMono } from "@/lib/fonts";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Clinova Research Intelligence Platform",
    template: "%s · Clinova",
  },
  description: "Evidence → Gaps → Hypotheses → Studies",
};

// Inline, synchronous, blocking script -- runs before first paint so the
// `dark` class is already on <html> by the time CSS applies. A React
// effect in theme-toggle.tsx would run after hydration and flash light
// mode for a frame on every reload; this is the standard fix for that,
// scoped to nothing but reading one localStorage key.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("clinova-theme");
    if (stored === "dark") document.documentElement.classList.add("dark");
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning is required here, not optional: the inline
    // script below mutates <html>'s class list (adding "dark") BEFORE React
    // hydrates, so the DOM's actual className legitimately differs from
    // what this JSX rendered on the server. Without this flag, React
    // throws a hydration-mismatch error (React error #441) the first time
    // a visitor has dark mode saved -- this is the same reason libraries
    // like next-themes require the identical flag for the identical
    // before-paint-script pattern. Scoped to just this one attribute, not
    // the whole subtree, so a real mismatch anywhere else still errors.
    <html
      lang="en"
      className={`${fontBody.variable} ${fontDisplay.variable} ${fontMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="font-sans">
        <TooltipProvider delayDuration={150}>{children}</TooltipProvider>
      </body>
    </html>
  );
}
