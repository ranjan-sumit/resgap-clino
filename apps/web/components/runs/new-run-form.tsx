"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, FileText, Loader2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/data/status-badge";
import { api, ApiError, type NewRunConfig, type RunJobView } from "@/lib/api";

const TERMINAL = ["succeeded", "failed"];

export function NewRunForm({ config }: { config: NewRunConfig }) {
  const router = useRouter();
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState(config.default_domain);
  const [interest, setInterest] = useState("");
  const [providerKey, setProviderKey] = useState(config.default_provider);
  const [model, setModel] = useState("");
  const [extractRefs, setExtractRefs] = useState(false);
  const [qualityEngine, setQualityEngine] = useState(false);
  const [gapChallenger, setGapChallenger] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<RunJobView | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const provider = config.providers.find((p) => p.key === providerKey);
  const keyMissing = provider ? !provider.api_key_present : false;
  const tooFew = files.length < config.min_papers;

  useEffect(() => {
    setModel(provider?.default_model ?? "");
  }, [provider?.default_model]);

  // Poll the job while it's in flight. Cleared on unmount so navigating away
  // mid-run doesn't leave a timer running against a dead component.
  useEffect(() => {
    if (!job || TERMINAL.includes(job.state)) return;
    pollRef.current = setInterval(async () => {
      try {
        setJob(await api.jobStatus(job.job_id));
      } catch {
        // A transient poll failure shouldn't kill the view -- the next tick
        // retries, and a genuinely dead job surfaces as a 404 the user can
        // still read below.
      }
    }, 1500);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job?.job_id, job?.state]);

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const pdfs = [...incoming].filter((f) => f.type === "application/pdf" || f.name.endsWith(".pdf"));
    setFiles((cur) => [...cur, ...pdfs].slice(0, config.max_papers));
  };

  const submit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      form.append("name", name);
      form.append("domain", domain);
      form.append("interest", interest);
      form.append("provider_key", providerKey);
      form.append("model", model);
      form.append("extract_refs", String(extractRefs));
      form.append("enable_quality_engine", String(qualityEngine));
      form.append("enable_gap_challenger", String(gapChallenger));
      setJob(await api.startRun(form));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (job) {
    return (
      <div className="space-y-6">
        <section className="rounded-xl border border-border/60 bg-card p-6 shadow-card">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              {job.state === "succeeded" ? (
                <CheckCircle2 className="h-5 w-5 text-semantic-success" aria-hidden />
              ) : job.state === "failed" ? (
                <AlertTriangle className="h-5 w-5 text-semantic-critical" aria-hidden />
              ) : (
                <Loader2 className="h-5 w-5 animate-spin text-clinova-blue" aria-hidden />
              )}
              <div>
                <p className="font-display text-xl text-clinova-deep">
                  {job.state === "succeeded"
                    ? "Run complete"
                    : job.state === "failed"
                      ? "Run failed"
                      : "Running…"}
                </p>
                <p className="mt-0.5 text-sm text-neutral">{job.message}</p>
              </div>
            </div>
            <span className="font-mono text-sm text-clinova-deep">{job.percent}%</span>
          </div>

          <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-gradient-to-r from-clinova-cyan to-clinova-blue transition-all duration-500"
              style={{ width: `${job.percent}%` }}
            />
          </div>

          {job.error && (
            <p className="mt-4 rounded-md border border-semantic-critical/30 bg-semantic-critical/5 px-3 py-2 text-sm text-slate-800">
              {job.error}
            </p>
          )}

          {job.gate_blocked && (
            <div className="mt-4 rounded-md border border-semantic-warning/30 bg-semantic-warning/5 px-3 py-2 text-sm text-slate-800">
              <p className="font-medium">Quality gate failed — gap analysis was skipped.</p>
              <ul className="mt-1 list-disc pl-5 text-xs">
                {job.gate_block_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-neutral">
                Everything already fetched (papers, references, evidence) was still saved.
              </p>
            </div>
          )}

          {job.state === "succeeded" && job.run_id && (
            <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border/60 pt-4">
              <p className="text-sm text-neutral">
                {job.n_gaps} gaps · {job.n_proposals} proposals
              </p>
              <div className="ml-auto flex gap-2">
                <Button asChild variant="outline" size="sm">
                  <Link href="/dashboard">Dashboard</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href={`/runs/${job.run_id}`}>Open run</Link>
                </Button>
              </div>
            </div>
          )}

          {job.state === "failed" && (
            <div className="mt-5 border-t border-border/60 pt-4">
              <Button variant="outline" size="sm" onClick={() => { setJob(null); router.refresh(); }}>
                Start over
              </Button>
            </div>
          )}
        </section>

        {job.trace.length > 0 && (
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
              Stages completed ({job.trace.length})
            </h2>
            <ol className="space-y-2 border-l border-border pl-4">
              {job.trace.map((t, i) => (
                <li key={i} className="relative rounded-lg border border-border/60 bg-card p-3 shadow-card">
                  <span className="absolute -left-[21px] top-4 h-2 w-2 rounded-full bg-clinova-blue" />
                  <p className="text-sm font-medium text-slate-800">{t.stage}</p>
                  <p className="mt-0.5 text-xs text-neutral">
                    <span className="font-medium">In:</span> {t.inputs}
                  </p>
                  <p className="text-xs text-neutral">
                    <span className="font-medium">Out:</span> {t.outputs}
                  </p>
                </li>
              ))}
            </ol>
          </section>
        )}

        {job.warnings.length > 0 && (
          <section className="rounded-lg border border-border/60 bg-card p-4 shadow-card">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-neutral">Warnings</p>
            <ul className="list-disc space-y-1 pl-4 text-xs text-neutral">
              {job.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Papers */}
      <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
          Papers ({files.length}/{config.max_papers})
        </p>
        <label
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}
          className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border py-10 transition-colors hover:border-clinova-blue/50 hover:bg-secondary/40"
        >
          <Upload className="h-6 w-6 text-neutral" aria-hidden />
          <span className="text-sm text-slate-800">Drop PDFs here, or click to choose</span>
          <span className="text-xs text-neutral">
            {config.min_papers}–{config.max_papers} papers · gap detection compares them against each other
          </span>
          <input
            type="file"
            accept="application/pdf"
            multiple
            className="hidden"
            onChange={(e) => addFiles(e.target.files)}
          />
        </label>

        {files.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {files.map((f, i) => (
              <li key={i} className="flex items-center gap-2 rounded-md border border-border/60 px-3 py-2 text-sm">
                <FileText className="h-4 w-4 shrink-0 text-neutral" aria-hidden />
                <span className="truncate text-slate-800">{f.name}</span>
                <span className="ml-auto shrink-0 font-mono text-xs text-neutral">
                  {Math.round(f.size / 1024).toLocaleString("en-US")} KB
                </span>
                <button
                  onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                  className="shrink-0 text-neutral hover:text-semantic-critical"
                  aria-label={`Remove ${f.name}`}
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Context */}
      <section className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-neutral">
            Run name
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Diabetes AI review"
            className="w-full rounded-md border border-border px-3 py-2 text-sm text-slate-800 outline-none focus:border-clinova-blue"
          />
          <p className="mt-1.5 text-xs text-neutral">Optional — a timestamped name is used if blank.</p>
        </div>
        <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-neutral">
            Domain
          </label>
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-clinova-blue"
          >
            {config.domains.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <p className="mt-1.5 text-xs text-neutral">Tunes extraction prompts and gap patterns.</p>
        </div>
      </section>

      <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
        <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-neutral">
          Research interest
        </label>
        <input
          value={interest}
          onChange={(e) => setInterest(e.target.value)}
          placeholder="What are you looking for? (optional)"
          className="w-full rounded-md border border-border px-3 py-2 text-sm text-slate-800 outline-none focus:border-clinova-blue"
        />
      </section>

      {/* Model */}
      <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Model</p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 block text-xs text-neutral">Provider</label>
            <select
              value={providerKey}
              onChange={(e) => setProviderKey(e.target.value)}
              className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-clinova-blue"
            >
              {config.providers.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}{p.api_key_present ? "" : " — no API key configured"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs text-neutral">Model</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-clinova-blue"
            >
              {(provider?.models ?? []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>
        {keyMissing && provider && (
          <p className="mt-3 rounded-md border border-semantic-warning/30 bg-semantic-warning/5 px-3 py-2 text-xs text-slate-800">
            No API key configured for {provider.label}. Set <code className="font-mono">{provider.api_key_env}</code> in
            {" "}<code className="font-mono">.env</code> and restart the API, or pick a provider that has one.
          </p>
        )}
      </section>

      {/* Optional stages */}
      <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">Optional stages</p>
        <div className="space-y-2.5 text-sm">
          {[
            [extractRefs, setExtractRefs, "Extract references",
             "Pulls each paper's citations and enriches them via academic APIs. Adds minutes."],
            [qualityEngine, setQualityEngine, "Corpus Quality Engine",
             "Second-parser cross-check (Docling) + quality gate. Heavy: roughly 90s per paper."],
            [gapChallenger, setGapChallenger, "Gap Challenger",
             "Search-coverage scoring and terminal status per gap. Extra searches per gap."],
          ].map(([value, setter, label, hint], i) => (
            <label key={i} className="flex cursor-pointer items-start gap-2.5">
              <input
                type="checkbox"
                checked={value as boolean}
                onChange={(e) => (setter as (v: boolean) => void)(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-clinova-blue"
              />
              <span>
                <span className="text-slate-800">{label as string}</span>
                <span className="block text-xs text-neutral">{hint as string}</span>
              </span>
            </label>
          ))}
        </div>
      </section>

      {error && (
        <p className="rounded-md border border-semantic-critical/30 bg-semantic-critical/5 px-3 py-2 text-sm text-slate-800">
          {error}
        </p>
      )}

      <div className="space-y-2 border-t border-border/60 pt-5">
        <div className="flex items-center gap-3">
          <Button onClick={submit} disabled={tooFew || keyMissing || submitting}>
            {submitting ? "Starting…" : "Start run"}
          </Button>
          {/* Blocking reason and cost disclosure are separate lines on
              purpose: the cost is true regardless of whether the form is
              ready yet, so hiding it behind a valid form meant the one
              warning that actually matters only appeared once the user was
              already committed. */}
          {(tooFew || keyMissing) && (
            <p className="text-xs text-neutral">
              {tooFew
                ? `Add at least ${config.min_papers} papers to start.`
                : "Pick a provider with a configured API key."}
            </p>
          )}
        </div>
        <p className="text-xs text-neutral">
          Starting a run makes real LLM calls against your configured provider and takes several
          minutes.
        </p>
      </div>

      <p className="text-xs text-neutral">{config.jobs_note}</p>
    </div>
  );
}
