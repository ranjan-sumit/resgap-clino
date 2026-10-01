"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import type { RunSummary } from "@/lib/api";

export function ComparePicker({
  runs,
  initialBaseline,
  initialCandidate,
}: {
  runs: RunSummary[];
  initialBaseline?: string;
  initialCandidate?: string;
}) {
  const [baseline, setBaseline] = useState(initialBaseline ?? "");
  const [candidate, setCandidate] = useState(initialCandidate ?? "");
  const router = useRouter();

  const canCompare = baseline !== "" && candidate !== "" && baseline !== candidate;

  return (
    <div className="rounded-lg border border-border bg-card p-5 shadow-card">
      <div className="grid grid-cols-[1fr_auto_1fr_auto] items-end gap-4">
        <div>
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-neutral">Baseline</label>
          <Select value={baseline} onValueChange={setBaseline}>
            <SelectTrigger>
              <SelectValue placeholder="Select baseline run" />
            </SelectTrigger>
            <SelectContent>
              {runs.map((r) => (
                <SelectItem key={r.run_id} value={r.run_id}>
                  {r.name} ({r.run_id.slice(0, 8)})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <ArrowRight className="mb-2 h-4 w-4 text-neutral" aria-hidden />
        <div>
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-neutral">Candidate</label>
          <Select value={candidate} onValueChange={setCandidate}>
            <SelectTrigger>
              <SelectValue placeholder="Select candidate run" />
            </SelectTrigger>
            <SelectContent>
              {runs.map((r) => (
                <SelectItem key={r.run_id} value={r.run_id}>
                  {r.name} ({r.run_id.slice(0, 8)})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          disabled={!canCompare}
          onClick={() =>
            router.push(`/runs/compare?baseline=${encodeURIComponent(baseline)}&candidate=${encodeURIComponent(candidate)}`)
          }
        >
          Compare
        </Button>
      </div>
      {baseline !== "" && baseline === candidate && (
        <p className="mt-3 text-xs text-semantic-warning">Baseline and candidate must be different runs.</p>
      )}
    </div>
  );
}
