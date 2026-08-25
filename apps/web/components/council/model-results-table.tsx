import type { ResearchCouncilView } from "@/lib/api";

type ModelRun = ResearchCouncilView["models_run"][number];

function formatValue(v: number | string): string {
  if (typeof v !== "number") return v;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// One clean table per model: rows are the metrics that model computed,
// columns are the real scenarios it ran (Base Case/Optimistic/Conservative)
// -- the direct replacement for a flat, unlabeled 12-tile number grid.
export function ModelResultsTable({ model, scenarios }: { model: ModelRun; scenarios: string[] }) {
  const metricLabels = [...new Set(scenarios.flatMap((sc) => Object.keys(model.metrics_by_scenario[sc] ?? {})))];
  const columns = scenarios.filter((sc) => model.metrics_by_scenario[sc]);

  if (metricLabels.length === 0) return null;

  return (
    <div className="rounded-lg border border-border/60 bg-card shadow-card">
      <div className="border-b border-border/60 px-4 py-3">
        <p className="font-medium text-clinova-deep">{model.model_used}</p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 text-xs uppercase tracking-wide text-neutral">
            <th className="px-4 py-2 text-left font-medium">Metric</th>
            {columns.map((sc) => (
              <th key={sc} className="px-4 py-2 text-right font-medium">
                {sc}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metricLabels.map((metric) => (
            <tr key={metric} className="border-b border-border/40 last:border-0">
              <td className="px-4 py-2 text-neutral">{metric}</td>
              {columns.map((sc) => (
                <td key={sc} className="px-4 py-2 text-right font-mono text-clinova-deep">
                  {model.metrics_by_scenario[sc]?.[metric] != null
                    ? formatValue(model.metrics_by_scenario[sc][metric])
                    : "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
