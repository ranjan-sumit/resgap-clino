"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/data/status-badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDuration } from "@/lib/format";
import type { RunSummary } from "@/lib/api";

// A run is only ever selectable up to 2 at a time -- the exact input
// Compare needs (baseline + candidate), never a bulk multi-select.

export function RunsTable({ runs }: { runs: RunSummary[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const router = useRouter();

  const toggle = (runId: string) => {
    setSelected((prev) => {
      if (prev.includes(runId)) return prev.filter((id) => id !== runId);
      if (prev.length >= 2) return prev;
      return [...prev, runId];
    });
  };

  const [baselineId, candidateId] = selected;
  const canCompare = selected.length === 2;

  const compareHref = useMemo(() => {
    if (!canCompare) return null;
    return `/runs/compare?baseline=${encodeURIComponent(baselineId)}&candidate=${encodeURIComponent(candidateId)}`;
  }, [canCompare, baselineId, candidateId]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-4 py-2.5 shadow-card">
        <p className="text-sm text-neutral">
          {selected.length === 0 && "Select two runs to compare — the first selected is the baseline."}
          {selected.length === 1 && "Select one more run as the candidate."}
          {selected.length === 2 && "Ready to compare."}
        </p>
        <Button
          size="sm"
          disabled={!canCompare}
          className="bg-gradient-to-r from-clinova-deep to-clinova-blue text-white shadow-glow-sm hover:opacity-90 disabled:opacity-40"
          onClick={() => compareHref && router.push(compareHref)}
        >
          Compare selected <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="overflow-hidden rounded-lg border border-border/60 bg-card shadow-card">
        <Table>
          <TableHeader>
            <TableRow className="border-border/60 hover:bg-transparent">
              <TableHead className="w-10" />
              <TableHead>Run</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Papers</TableHead>
              <TableHead className="text-right">Gaps</TableHead>
              <TableHead className="text-right">Proposals</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Quality gates</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => {
              const isSelected = selected.includes(run.run_id);
              const isDisabled = !isSelected && selected.length >= 2;
              return (
                <TableRow
                  key={run.run_id}
                  data-state={isSelected ? "selected" : undefined}
                  className={
                    isSelected
                      ? "border-border/60 bg-clinova-cyan/[0.06] hover:bg-clinova-cyan/[0.08]"
                      : "border-border/60 hover:bg-surface/60"
                  }
                >
                  <TableCell>
                    <Checkbox
                      checked={isSelected}
                      disabled={isDisabled}
                      onCheckedChange={() => toggle(run.run_id)}
                      aria-label={`Select ${run.name} for comparison`}
                    />
                  </TableCell>
                  <TableCell>
                    <Link href={`/runs/${run.run_id}`} className="font-medium text-clinova-deep hover:underline">
                      {run.name}
                    </Link>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <p className="cursor-help font-mono text-xs text-neutral">{run.run_id.slice(0, 12)}</p>
                      </TooltipTrigger>
                      <TooltipContent className="font-mono">{run.run_id}</TooltipContent>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <StatusBadge chip={run.status} size="sm" />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-neutral">{run.created_at}</TableCell>
                  <TableCell className="text-right font-mono text-sm text-clinova-deep">{run.n_papers}</TableCell>
                  <TableCell className="text-right font-mono text-sm text-clinova-deep">{run.n_gaps}</TableCell>
                  <TableCell className="text-right font-mono text-sm text-clinova-deep">{run.n_proposals}</TableCell>
                  <TableCell className="text-sm text-neutral">{formatDuration(run.duration_seconds)}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {run.quality_gates.map((g) => (
                        <StatusBadge key={g.code} chip={g} size="sm" />
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
