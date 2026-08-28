import type { Metadata } from "next";
import { RunsTable } from "@/components/runs/runs-table";
import { EmptyState } from "@/components/data/empty-state";
import Link from "next/link";
import { PageHero } from "@/components/shell/page-hero";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { common } from "@/lib/copy";

export const metadata: Metadata = { title: "Runs" };

export default async function RunsPage() {
  const { runs, empty_reason } = await api.listRuns();

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHero
        eyebrow="Engineering"
        title="Runs"
        description="Every pipeline run recorded in the registry, newest first."
        actions={
          <Button asChild>
            <Link href="/runs/new">New run</Link>
          </Button>
        }
      />

      {runs.length === 0 ? (
        <EmptyState
          title="No runs yet"
          description={empty_reason ?? common.no_projects_body}
          action={{ label: "Open Streamlit", href: "http://localhost:8501" }}
        />
      ) : (
        <RunsTable runs={runs} />
      )}
    </div>
  );
}
