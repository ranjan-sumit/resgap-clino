import { HelpCircle } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { VersionField } from "@/lib/api";

export function VersionFieldView({ field }: { field: VersionField }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <span className="text-neutral">{field.label}</span>
      {field.recorded ? (
        <span className="rounded-md bg-clinova-light/10 px-1.5 py-0.5 font-mono text-clinova-deep">
          {field.value}
        </span>
      ) : (
        <span className="flex items-center gap-1.5 italic text-neutral">
          Not recorded
          <Tooltip>
            <TooltipTrigger asChild>
              <HelpCircle aria-hidden className="h-3.5 w-3.5 cursor-help" />
            </TooltipTrigger>
            <TooltipContent className="max-w-sm">{field.note}</TooltipContent>
          </Tooltip>
        </span>
      )}
    </div>
  );
}
