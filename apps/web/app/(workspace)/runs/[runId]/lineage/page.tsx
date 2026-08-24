import Link from "next/link";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/data/empty-state";
import { ErrorState } from "@/components/data/error-state";
import { TechnicalDiagram } from "@/components/lineage/technical-diagram";
import { GapChainCard } from "@/components/lineage/gap-chain";
import { api, ApiError } from "@/lib/api";

export default async function LineagePage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;

  let technical, scientific;
  try {
    [technical, scientific] = await Promise.all([
      api.technicalLineage(runId),
      api.scientificLineage(runId),
    ]);
  } catch (err) {
    if (err instanceof ApiError) {
      return <ErrorState title="Lineage not available" detail={err.message} retryHref="/runs" />;
    }
    throw err;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <Link href={`/runs/${runId}`} className="text-sm text-neutral hover:underline">
          &larr; Run detail
        </Link>
        <h1 className="mt-2 font-display text-3xl text-clinova-deep">Lineage</h1>
        <p className="mt-1 font-mono text-xs text-neutral">{runId}</p>
      </div>

      <Tabs defaultValue="technical">
        <TabsList>
          <TabsTrigger value="technical">Technical</TabsTrigger>
          <TabsTrigger value="scientific">Scientific ({scientific.gaps.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="technical" className="pt-4">
          <TechnicalDiagram lineage={technical} />
        </TabsContent>

        <TabsContent value="scientific" className="space-y-3 pt-4">
          {scientific.identity_note && (
            <p className="text-sm italic text-neutral">{scientific.identity_note}</p>
          )}
          {scientific.gaps.length === 0 ? (
            <EmptyState
              title="No traceable gaps"
              description="No gaps on this run have a resolvable identity to trace a scientific chain for."
            />
          ) : (
            scientific.gaps.map((chain, i) => <GapChainCard key={chain.gap_id ?? i} chain={chain} />)
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
