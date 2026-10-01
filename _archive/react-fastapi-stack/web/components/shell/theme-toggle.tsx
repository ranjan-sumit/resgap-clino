"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "clinova-theme";

// Manual, per-user opt-in only -- never reads `prefers-color-scheme` (see
// globals.css's comment: no silent OS-driven switching for this app).
// The actual before-paint class application lives in app/layout.tsx's
// inline script; this component only owns the toggle affordance and
// keeps its own `isDark` state in sync with the class that's already
// there by the time this mounts.
export function ThemeToggle({ className }: { className?: string }) {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
    } catch {
      // Private-browsing/storage-blocked: the toggle still works for this
      // session, it just won't persist across reloads -- acceptable, not
      // worth surfacing an error for a cosmetic preference.
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      aria-pressed={isDark}
      className={cn(
        "flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-chrome-muted transition-colors hover:bg-white/[0.06] hover:text-chrome-text",
        className,
      )}
    >
      {isDark ? <Sun aria-hidden className="h-3.5 w-3.5" /> : <Moon aria-hidden className="h-3.5 w-3.5" />}
      {isDark ? "Light mode" : "Dark mode"}
    </button>
  );
}
