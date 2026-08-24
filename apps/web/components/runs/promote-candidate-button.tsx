"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { api, ApiError, type RunComparison } from "@/lib/api";

export function PromoteCandidateButton({
  candidateRunId,
  promotion,
}: {
  candidateRunId: string;
  promotion: RunComparison["promotion"];
}) {
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  // The real gate: eligible alone is vacuously true when neither run
  // recorded evaluation metrics (evaluate_promotion({}, {}) -- see
  // apps/api/services/compare_service.py). can_evaluate is what actually
  // matters, and there must be a real registered artifact to promote.
  const canPromote = promotion.can_evaluate && promotion.eligible && !!promotion.candidate_artifact_id;

  return (
    <div className="mt-4">
      <Button
        disabled={!canPromote || isPending}
        onClick={() =>
          startTransition(async () => {
            setError(null);
            try {
              await api.promoteRun(candidateRunId, "CANDIDATE");
              router.refresh();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Promotion failed.");
            }
          })
        }
      >
        {isPending ? "Promoting…" : "Promote candidate"}
      </Button>
      <p className="mt-1.5 text-xs text-neutral">
        {canPromote
          ? "Promotes the candidate run's pipeline artifact to CANDIDATE status."
          : "Disabled until the promotion gate above is eligible and both runs can be evaluated."}
      </p>
      {error && <p className="mt-1 text-xs text-semantic-critical">{error}</p>}
    </div>
  );
}
