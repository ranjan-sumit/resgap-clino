import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  HelpCircle,
  OctagonX,
  SearchX,
  ShieldCheck,
} from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { StatusChip } from "@/lib/api";

// The concrete, never-bare-color implementation of
// 02-ux-specification.md §6/NFR-8: every status renders as text + a
// distinct icon shape per status family + color, never color alone.
// There is no variant of this component that omits the label.
const TONE_CLASSES: Record<StatusChip["tone"], string> = {
  positive: "text-semantic-success ring-semantic-success/25 bg-semantic-success/[0.08]",
  caution: "text-semantic-warning ring-semantic-warning/25 bg-semantic-warning/[0.08]",
  critical: "text-semantic-critical ring-semantic-critical/25 bg-semantic-critical/[0.08]",
  neutral: "text-neutral ring-border bg-muted",
  unknown: "text-clinova-deep ring-clinova-light/40 bg-clinova-light/[0.08]",
};

// On a dark surface (PageHero) the light-background tones above go
// near-invisible (dark text on dark blue) -- a real contrast bug, not
// cosmetic. This is the inverse palette for that context, same icon/tone
// mapping, never a variant that drops the label.
const TONE_CLASSES_ON_DARK: Record<StatusChip["tone"], string> = {
  positive: "text-white ring-semantic-success/50 bg-semantic-success/20",
  caution: "text-white ring-semantic-warning/50 bg-semantic-warning/20",
  critical: "text-white ring-semantic-critical/50 bg-semantic-critical/20",
  neutral: "text-white/80 ring-white/25 bg-white/10",
  unknown: "text-white ring-clinova-cyan/50 bg-clinova-cyan/20",
};

const ICONS: Record<StatusChip["icon"], typeof CheckCircle2> = {
  "check-circle": CheckCircle2,
  "alert-triangle": AlertTriangle,
  "octagon-x": OctagonX,
  "circle-dashed": CircleDashed,
  "help-circle": HelpCircle,
  "shield-check": ShieldCheck,
  "search-x": SearchX,
};

export function StatusBadge({
  chip,
  size = "md",
  onDark = false,
}: {
  chip: StatusChip;
  size?: "sm" | "md";
  onDark?: boolean;
}) {
  const Icon = ICONS[chip.icon];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 font-medium ring-1 ring-inset transition-shadow hover:shadow-sm",
            (onDark ? TONE_CLASSES_ON_DARK : TONE_CLASSES)[chip.tone],
            size === "sm" ? "text-xs" : "text-sm",
          )}
        >
          <Icon aria-hidden className={size === "sm" ? "h-3 w-3 shrink-0" : "h-3.5 w-3.5 shrink-0"} />
          <span>{chip.label}</span>
          <span className="sr-only"> — {chip.reason}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">{chip.reason}</TooltipContent>
    </Tooltip>
  );
}
