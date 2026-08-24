"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, ApiError } from "@/lib/api";

export function PromoteButton({ runId, nextStatuses }: { runId: string; nextStatuses: string[] }) {
  const [target, setTarget] = useState(nextStatuses[0] ?? "");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  if (nextStatuses.length === 0) return null;

  return (
    <div className="flex items-center gap-2">
      <Select value={target} onValueChange={setTarget}>
        <SelectTrigger className="h-7 w-[130px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {nextStatuses.map((s) => (
            <SelectItem key={s} value={s}>
              {s}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        size="sm"
        disabled={isPending || !target}
        onClick={() =>
          startTransition(async () => {
            setError(null);
            try {
              await api.promoteRun(runId, target as "CANDIDATE" | "CHAMPION" | "ARCHIVED");
              router.refresh();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Promotion failed.");
            }
          })
        }
      >
        {isPending ? "Promoting…" : "Promote"}
      </Button>
      {error && <span className="text-xs text-semantic-critical">{error}</span>}
    </div>
  );
}
