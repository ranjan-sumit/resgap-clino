import { ModelResultsTable } from "@/components/council/model-results-table";
import { SensitivityBars } from "@/components/council/sensitivity-bars";
import { EmptyState } from "@/components/data/empty-state";
import type { ResearchCouncilView } from "@/lib/api";

export function hasModelling(council: ResearchCouncilView): boolean {
  return council.models_run.length > 0 || council.sensitivity_ranking.length > 0;
}

// Shared by the Research Council page's "Computational modelling" tab and
// the dedicated /council/modelling screen, so the two can never drift.
export function ModellingPanel({ council }: { council: ResearchCouncilView }) {
  if (!hasModelling(council)) {
    return (
      <EmptyState
        title="No computational modelling for this run"
        description="Simulation requires at least one extracted parameter with usable confidence -- none were available for this run."
      />
    );
  }

  return (
    <div className="space-y-6">
      {council.model_selection && (
        <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">
            Model selection · {council.model_selection.confidence} confidence
          </p>
          <p className="text-xl font-semibold tracking-tight text-clinova-deep">{council.model_selection.selected_model}</p>
          <p className="mt-2 text-sm text-neutral">{council.model_selection.rationale}</p>
        </section>
      )}

      {council.models_run.length > 0 && (
        <section>
          <p className="mb-3 text-sm text-neutral">
            {council.models_run.length} algorithm{council.models_run.length === 1 ? "" : "s"} run across{" "}
            {council.scenarios_run.length} scenarios ({council.scenarios_run.join(", ")}).
          </p>
          <div className="space-y-4">
            {council.models_run.map((m) => (
              <ModelResultsTable key={m.model_key} model={m} scenarios={council.scenarios_run} />
            ))}
          </div>
        </section>
      )}

      <SensitivityBars drivers={council.sensitivity_ranking} />
    </div>
  );
}
