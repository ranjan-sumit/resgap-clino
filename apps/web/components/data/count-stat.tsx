import { HelpCircle } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { CountStat } from "@/lib/api";

// `hint` is optional and only meant for counts whose label alone is real
// jargon a reader can't interpret without domain context (e.g. "Orphan
// Concepts") -- self-explanatory counts like "Papers" or "Gaps" don't need
// it and shouldn't get a tooltip icon cluttering an otherwise plain number.
export function CountStatView({ stat, hint }: { stat: CountStat; hint?: string }) {
  return (
    <div className="group relative overflow-hidden rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
      <div className="absolute inset-x-0 top-0 h-[3px] bg-accent-line opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-neutral">
        {stat.label}
        {hint && (
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle aria-hidden className="h-3 w-3 cursor-help" />
            </TooltipTrigger>
            <TooltipContent className="max-w-xs normal-case">{hint}</TooltipContent>
          </Tooltip>
        )}
      </div>
      <div className="font-display text-clinova-deep text-4xl">{stat.display}</div>
    </div>
  );
}
