import { redirect } from "next/navigation";
import { EmptyState } from "@/components/data/empty-state";
import { api } from "@/lib/api";

export default async function LineageResolverPage() {
  const { runs } = await api.listRuns(1);

  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs to trace yet"
        description="Lineage becomes available once at least one run has been recorded."
        action={{ label: "View runs", href: "/runs" }}
      />
    );
  }

  redirect(`/runs/${runs[0].run_id}/lineage`);
}
