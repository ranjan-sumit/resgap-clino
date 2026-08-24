import { RunsTable } from "@/components/runs/runs-table";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

export default async function RunsPage() {
  const { runs, empty_reason } = await api.listRuns();

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="font-display text-3xl text-clinova-deep">Runs</h1>
        <p className="mt-1 text-sm text-neutral">Every pipeline run recorded in the registry, newest first.</p>
      </div>

      {runs.length === 0 ? (
        <EmptyState
          title="No runs yet"
          description={empty_reason ?? "Runs created in the Streamlit workspace appear here automatically."}
          action={{ label: "Open Streamlit", href: "http://localhost:8501" }}
        />
      ) : (
        <RunsTable runs={runs} />
      )}
    </div>
  );
}
