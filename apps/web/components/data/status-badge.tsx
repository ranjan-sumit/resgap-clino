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
  positive: "text-semantic-success ring-semantic-success/30 bg-semantic-success/10",
  caution: "text-semantic-warning ring-semantic-warning/30 bg-semantic-warning/10",
  critical: "text-semantic-critical ring-semantic-critical/30 bg-semantic-critical/10",
  neutral: "text-neutral ring-border bg-muted",
  unknown: "text-clinova-deep ring-clinova-light bg-clinova-light/10",
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

export function StatusBadge({ chip, size = "md" }: { chip: StatusChip; size?: "sm" | "md" }) {
  const Icon = ICONS[chip.icon];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-0.5 font-medium ring-1 ring-inset",
            TONE_CLASSES[chip.tone],
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
