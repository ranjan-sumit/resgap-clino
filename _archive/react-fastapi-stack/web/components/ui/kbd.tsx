import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

// Keyboard-shortcut chip -- the small "⌘K" affordance inside search pills
// and menu rows. One component so every shortcut reads identically.
export function Kbd({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <kbd
      className={cn(
        "rounded border border-border bg-white px-1 text-[10px] font-medium text-neutral",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
