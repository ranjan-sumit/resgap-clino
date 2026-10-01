"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, FlaskConical, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, ApiError, type RunJobView } from "@/lib/api";

const TERMINAL = ["succeeded", "failed"];

/**
 * Trigger + live progress for the Computational Lab (Clinova Phase 5, first
 * API-triggerable version -- previously only runnable from the Streamlit
 * sidebar). Shown in place of the plain "No council run yet" EmptyState on
 * Research Council / Computational Modelling when there's a real basis run
 * to run the lab against.
 *
 * Same poll-and-render shape as components/runs/new-run-form.tsx (reused
 * deliberately, not reinvented) -- 1500ms interval against the shared job
 * registry, cleared on unmount. On success, navigates to
 * `/workspace?tab=...&run={job.run_id}` so every panel picks up the run
 * that now actually has Computational Lab output, then refreshes the
 * Server Component data.
 */
export function RunComputationalLab({ runId, tab }: { runId: string; tab: "council" | "modelling" }) {
  const router = useRouter();
  const [job, setJob] = useState<RunJobView | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!job || TERMINAL.includes(job.state)) return;
    pollRef.current = setInterval(async () => {
      try {
        const next = await api.jobStatus(job.job_id);
        setJob(next);
        if (next.state === "succeeded" && next.run_id) {
          router.push(`/workspace?tab=${tab}&run=${next.run_id}`);
          router.refresh();
        }
      } catch {
        // Transient poll failure -- next tick retries.
      }
    }, 1500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job?.job_id, job?.state, router, tab]);

  const start = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const form = new FormData();
      form.append("n_council_runs", "2");
      setJob(await api.runComputationalLab(runId, form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (job) {
    return (
      <div className="w-full max-w-md space-y-3 rounded-xl border border-dashed border-clinova-light/40 bg-white px-8 py-10 text-center shadow-card dark:border-dark-border dark:bg-dark-card">
        <div className="flex items-center justify-center gap-2.5">
          {job.state === "succeeded" ? (
            <CheckCircle2 className="h-5 w-5 text-semantic-success" aria-hidden />
          ) : job.state === "failed" ? (
            <AlertTriangle className="h-5 w-5 text-semantic-critical" aria-hidden />
          ) : (
            <Loader2 className="h-5 w-5 animate-spin text-clinova-blue dark:text-dark-primary" aria-hidden />
          )}
          <p className="text-sm font-semibold text-clinova-deep dark:text-dark-foreground">
            {job.state === "succeeded" ? "Done — loading results…" : job.state === "failed" ? "Failed" : job.message}
          </p>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted dark:bg-dark-secondary">
          <div
            className="h-full rounded-full bg-clinova-blue transition-all duration-500 dark:bg-dark-primary"
            style={{ width: `${job.percent}%` }}
          />
        </div>
        {job.error && (
          <p className="rounded-md border border-semantic-critical/30 bg-semantic-critical/5 px-3 py-2 text-left text-xs text-foreground">
            {job.error}
          </p>
        )}
        {job.state === "failed" && (
          <Button variant="outline" size="sm" onClick={() => setJob(null)}>
            Try again
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-md flex-col items-center gap-3 rounded-xl border border-dashed border-clinova-light/40 bg-white px-8 py-10 text-center shadow-card dark:border-dark-border dark:bg-dark-card">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-clinova-cyan/10 dark:bg-dark-primary/10">
        <FlaskConical aria-hidden className="h-5 w-5 text-clinova-blue dark:text-dark-primary" />
      </div>
      <p className="text-sm font-semibold text-clinova-deep dark:text-dark-foreground">No Computational Lab run yet</p>
      <p className="max-w-sm text-sm leading-relaxed text-neutral dark:text-dark-muted-foreground">
        Extracts real parameters from your papers, runs cross-paper discovery and multi-algorithm
        simulation, then synthesises findings via the LLM research council. Makes real LLM calls and
        takes several minutes.
      </p>
      {error && (
        <p className="rounded-md border border-semantic-critical/30 bg-semantic-critical/5 px-3 py-2 text-xs text-foreground">
          {error}
        </p>
      )}
      <Button onClick={start} disabled={submitting} className="mt-1">
        {submitting && <Loader2 className="animate-spin" aria-hidden />}
        {submitting ? "Starting…" : "Run Computational Lab"}
      </Button>
    </div>
  );
}
