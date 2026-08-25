import type { Metadata } from "next";
import Link from "next/link";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { PageHero } from "@/components/shell/page-hero";
import { StatusBadge } from "@/components/data/status-badge";
import { EmptyState } from "@/components/data/empty-state";
import { PromoteButton } from "@/components/artifacts/promote-button";
import { api } from "@/lib/api";

export const metadata: Metadata = { title: "Versions" };

export default async function VersionsPage() {
  const { artifacts, empty_reason } = await api.artifacts();

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHero
        eyebrow="Engineering"
        title="Versions"
        description="The Research Artifact Registry — every versioned artifact and its lifecycle status."
      />

      {artifacts.length === 0 ? (
        <EmptyState title="No artifacts yet" description={empty_reason ?? "No artifacts have been registered yet."} />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border/60 bg-card shadow-card">
          <Table>
            <TableHeader>
              <TableRow className="border-border/60 hover:bg-transparent">
                <TableHead>Artifact</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Project</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {artifacts.map((a) => (
                <TableRow key={a.artifact_id} className="border-border/60 hover:bg-surface/60">
                  <TableCell className="font-mono text-xs text-clinova-deep">
                    {a.run_id ? (
                      <Link href={`/runs/${a.run_id}`} className="hover:underline">
                        {a.artifact_id}
                      </Link>
                    ) : (
                      a.artifact_id
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-neutral">{a.artifact_type}</TableCell>
                  <TableCell>
                    <StatusBadge chip={a.status} size="sm" />
                  </TableCell>
                  <TableCell className="text-sm text-neutral">{a.project_id}</TableCell>
                  <TableCell className="font-mono text-xs text-neutral">{a.created_at.slice(0, 19)}</TableCell>
                  <TableCell>
                    {a.run_id && <PromoteButton runId={a.run_id} nextStatuses={a.next_legal_statuses} />}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
