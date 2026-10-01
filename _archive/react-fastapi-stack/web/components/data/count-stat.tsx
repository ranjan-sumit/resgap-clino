import { HelpCircle } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { statIcon } from "@/components/data/stat-icons";
import type { CountStat } from "@/lib/api";

// `hint` is optional and only meant for counts whose label alone is real
// jargon a reader can't interpret without domain context (e.g. "Orphan
// Concepts") -- self-explanatory counts like "Papers" or "Gaps" don't need
// it and shouldn't get a tooltip icon cluttering an otherwise plain number.
export function CountStatView({ stat, hint }: { stat: CountStat; hint?: string }) {
  const Icon = statIcon(stat.key);
  return (
    <div className="group relative overflow-hidden rounded-lg border border-border/60 bg-card p-5 shadow-card transition-all duration-200 hover:-translate-y-px hover:shadow-card-hover">
      <div className="absolute inset-x-0 top-0 h-[3px] bg-accent-line opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
      <div className="mb-2.5 flex items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-clinova-blue/10 text-clinova-blue">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="flex min-w-0 items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-neutral">
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
      </div>
      <div className="text-[28px] font-semibold tabular-nums tracking-tight text-clinova-deep">{stat.display}</div>
    </div>
  );
}
