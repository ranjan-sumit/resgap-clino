import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RunComparison } from "@/lib/api";

type MetricComparison = RunComparison["metrics"][number];

// Never a bare colored arrow -- always the arrow PLUS the words
// "better"/"worse"/"within tolerance" alongside the numeric delta.
export function MetricDelta({ metric }: { metric: MetricComparison }) {
  if (metric.baseline == null || metric.candidate == null) {
    return <span className="text-sm italic text-neutral">Not measured</span>;
  }
  if (metric.better === "equal") {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-neutral">
        <Minus className="h-3.5 w-3.5" aria-hidden /> unchanged
      </span>
    );
  }

  const improved = metric.better === "candidate";
  const label =
    metric.verdict === "regressed" ? "worse" : improved ? "better" : metric.better === "unknown" ? "" : "worse";
  const pct = metric.delta_pct != null ? `${(metric.delta_pct * 100).toFixed(1)}%` : null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-sm font-medium",
        metric.verdict === "regressed" ? "text-semantic-critical" : "text-semantic-success",
      )}
    >
      {metric.candidate > metric.baseline ? (
        <ArrowUp className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <ArrowDown className="h-3.5 w-3.5" aria-hidden />
      )}
      {pct && <span>{pct}</span>}
      <span>{label}</span>
    </span>
  );
}
