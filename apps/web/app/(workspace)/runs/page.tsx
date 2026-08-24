import { RunsTable } from "@/components/runs/runs-table";
import { EmptyState } from "@/components/data/empty-state";
import { PageHero } from "@/components/shell/page-hero";
import { api } from "@/lib/api";

export default async function RunsPage() {
  const { runs, empty_reason } = await api.listRuns();

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHero
        eyebrow="Engineering"
        title="Runs"
        description="Every pipeline run recorded in the registry, newest first."
      />

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
