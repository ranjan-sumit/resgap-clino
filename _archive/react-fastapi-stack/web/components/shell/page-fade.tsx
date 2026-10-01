"use client";

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

// Replays the existing fade-up keyframe on every navigation, so each screen
// settles in rather than popping. The wrapper itself is inert -- it only
// re-triggers the CSS animation the globals already define (and that the
// reduced-motion media query already disables).
export function PageFade({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.classList.remove("animate-fade-up");
    // Force a reflow so the animation restarts even when navigating between
    // two pages that both mount this wrapper.
    void el.offsetWidth;
    el.classList.add("animate-fade-up");
  }, [pathname]);

  return (
    <div ref={ref} className="animate-fade-up">
      {children}
    </div>
  );
}
