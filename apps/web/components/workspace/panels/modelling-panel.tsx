import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { ModellingPanel as ModellingBody } from "@/components/council/modelling-panel";
import { api } from "@/lib/api";
import type { PanelProps } from "@/components/workspace/panel-props";

// Shares components/council/modelling-panel.tsx with the Research Council
// tab and the standalone /council/modelling route, so the three can't drift.
export async function ComputationalModellingPanel({ projectId, runId }: PanelProps) {
  const council = await api.council(projectId, runId);

  if (council.empty_reason) {
    return <EmptyState title="No council run yet" description={council.empty_reason} />;
  }

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-5 gap-4">
        {council.params_summary.map((c) => (
          <CountStatView key={c.key} stat={c} />
        ))}
      </div>
      {council.n_excluded_low_confidence > 0 && (
        <p className="text-xs text-neutral">
          {council.n_excluded_low_confidence} parameter(s) excluded from simulation — confidence too low.
        </p>
      )}

      <ModellingBody council={council} />
    </div>
  );
}
