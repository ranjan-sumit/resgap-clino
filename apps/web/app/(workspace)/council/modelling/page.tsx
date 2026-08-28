import type { Metadata } from "next";
import Link from "next/link";
import { PageHero } from "@/components/shell/page-hero";
import { CountStatView } from "@/components/data/count-stat";
import { EmptyState } from "@/components/data/empty-state";
import { ModellingPanel } from "@/components/council/modelling-panel";
import { api } from "@/lib/api";
import { getSelectedProject } from "@/lib/project";

export const metadata: Metadata = { title: "Computational Modelling" };

export default async function ComputationalModellingPage() {
  const project = await getSelectedProject();
  if (!project) {
    return <EmptyState title="No projects yet" description="Runs created in the Streamlit workspace appear here automatically." />;
  }

  const council = await api.council(project.project_id);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHero
        eyebrow="Intelligence"
        title="Computational Modelling"
        description="Simulation results from the parameters extracted across this project's papers — which algorithms ran, what each produced per scenario, and which parameters moved the outcome most."
        actions={
          <Link
            href="/council"
            className="rounded-md border border-border px-3 py-1.5 text-sm text-clinova-deep hover:bg-secondary"
          >
            Research Council &rarr;
          </Link>
        }
      />

      {council.empty_reason ? (
        <EmptyState title="No council run yet" description={council.empty_reason} />
      ) : (
        <>
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

          <ModellingPanel council={council} />
        </>
      )}
    </div>
  );
}
