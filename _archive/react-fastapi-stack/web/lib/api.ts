import type { components } from "@/../../packages/contracts/typescript/api";

export type RunSummary = components["schemas"]["RunSummary"];
export type RunListResponse = components["schemas"]["RunListResponse"];
export type RunDetail = components["schemas"]["RunDetail"];
export type RunManifestView = components["schemas"]["RunManifestView"];
export type TraceStep = components["schemas"]["TraceStep"];
export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type ProjectDashboard = components["schemas"]["ProjectDashboard"];
export type WorkspaceHeader = components["schemas"]["WorkspaceHeader"];
export type RunComparison = components["schemas"]["RunComparison"];
export type TechnicalLineage = components["schemas"]["TechnicalLineage"];
export type ScientificLineage = components["schemas"]["ScientificLineage"];
export type StatusChip = components["schemas"]["StatusChip"];
export type Measure = components["schemas"]["Measure"];
export type CountStat = components["schemas"]["CountStat"];
export type VersionField = components["schemas"]["VersionField"];
export type CorpusView = components["schemas"]["CorpusView"];
export type QualityView = components["schemas"]["QualityView"];
export type PaperCompleteness = components["schemas"]["PaperCompleteness"];
export type TrustStatusCount = components["schemas"]["TrustStatusCount"];
export type PaperDetail = components["schemas"]["PaperDetail"];
export type RunOption = components["schemas"]["RunOption"];
export type RunJobView = components["schemas"]["RunJobView"];
export type NewRunConfig = components["schemas"]["NewRunConfig"];
export type SearchResponse = components["schemas"]["SearchResponse"];
export type SearchHit = components["schemas"]["SearchHit"];
export type EvidenceView = components["schemas"]["EvidenceView"];
export type GraphView = components["schemas"]["GraphView"];
export type ChallengerView = components["schemas"]["ChallengerView"];
export type ResearchCouncilView = components["schemas"]["ResearchCouncilView"];
export type ArtifactListResponse = components["schemas"]["ArtifactListResponse"];
export type ArtifactView = components["schemas"]["ArtifactView"];

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

// Server Components use API_BASE_URL (server-side only, no CORS
// concern); client-side fetches (Compare's run picker, any future
// client refresh) use NEXT_PUBLIC_API_BASE_URL. Both default to the
// documented dev port (see apps/README.md).
const BASE =
  typeof window === "undefined"
    ? process.env.API_BASE_URL || "http://localhost:8000"
    : process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || `Request to ${path} failed with ${res.status}`);
  }
  return res.json();
}

// "?run_id=..." or "". A helper rather than inline so no call site has to
// remember whether run_id is the first query param on that particular path.
function runParam(runId?: string): string {
  return runId ? `?run_id=${encodeURIComponent(runId)}` : "";
}

export const api = {
  health: () => get<components["schemas"]["HealthResponse"]>("/api/health"),
  listProjects: () => get<ProjectSummary[]>("/api/projects"),
  getDashboard: (projectId: string, runId?: string, recentLimit?: number) => {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    if (recentLimit) params.set("recent_limit", String(recentLimit));
    const qs = params.toString();
    return get<ProjectDashboard>(
      `/api/projects/${encodeURIComponent(projectId)}/dashboard${qs ? `?${qs}` : ""}`,
    );
  },
  // Slim header for /workspace. See WorkspaceHeader in the API for why
  // this is not getDashboard().
  workspaceHeader: (projectId: string, runId?: string) =>
    get<WorkspaceHeader>(`/api/projects/${encodeURIComponent(projectId)}/workspace${runParam(runId)}`),
  listRuns: (limit = 50) => get<RunListResponse>(`/api/runs?limit=${limit}`),
  // Cheap sidebar list. See RunOption in the API for why this is not listRuns().
  runOptions: (limit = 50) => get<RunOption[]>(`/api/run-options?limit=${limit}`),
  getRun: (runId: string) => get<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`),
  compare: (baseline: string, candidate: string) =>
    get<RunComparison>(
      `/api/compare?baseline=${encodeURIComponent(baseline)}&candidate=${encodeURIComponent(candidate)}`,
    ),
  technicalLineage: (runId: string) =>
    get<TechnicalLineage>(`/api/runs/${encodeURIComponent(runId)}/lineage/technical`),
  scientificLineage: (runId: string, gapId?: string) =>
    get<ScientificLineage>(
      `/api/runs/${encodeURIComponent(runId)}/lineage/scientific${gapId ? `?gap_id=${encodeURIComponent(gapId)}` : ""}`,
    ),
  corpus: (projectId: string, runId?: string) =>
    get<CorpusView>(`/api/projects/${encodeURIComponent(projectId)}/corpus${runParam(runId)}`),
  paper: (projectId: string, filename: string, runId?: string) =>
    get<PaperDetail>(
      `/api/projects/${encodeURIComponent(projectId)}/corpus/papers/${encodeURIComponent(filename)}${runParam(runId)}`,
    ),
  quality: (projectId: string, runId?: string) =>
    get<QualityView>(`/api/projects/${encodeURIComponent(projectId)}/quality${runParam(runId)}`),
  evidence: (projectId: string, runId?: string) =>
    get<EvidenceView>(`/api/projects/${encodeURIComponent(projectId)}/evidence${runParam(runId)}`),
  graph: (projectId: string, runId?: string) =>
    get<GraphView>(`/api/projects/${encodeURIComponent(projectId)}/graph${runParam(runId)}`),
  challenger: (projectId: string, runId?: string) =>
    get<ChallengerView>(`/api/projects/${encodeURIComponent(projectId)}/challenger${runParam(runId)}`),
  council: (projectId: string, runId?: string) =>
    get<ResearchCouncilView>(`/api/projects/${encodeURIComponent(projectId)}/council${runParam(runId)}`),
  artifacts: () => get<ArtifactListResponse>("/api/artifacts"),
  reportUrl: (runId: string, format: "html" | "pdf" | "markdown" | "json") =>
    `${BASE}/api/runs/${encodeURIComponent(runId)}/report?format=${format}`,
  search: (projectId: string, q: string, limit = 20) =>
    get<SearchResponse>(
      `/api/projects/${encodeURIComponent(projectId)}/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  newRunConfig: () => get<NewRunConfig>("/api/runs/new/config"),
  jobStatus: (jobId: string) => get<RunJobView>(`/api/jobs/${encodeURIComponent(jobId)}`),
  startRun: async (form: FormData): Promise<RunJobView> => {
    const res = await fetch(`${BASE}/api/runs/new`, { method: "POST", body: form });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail || `Starting the run failed with ${res.status}`);
    }
    return res.json();
  },
  runComputationalLab: async (runId: string, form: FormData): Promise<RunJobView> => {
    const res = await fetch(`${BASE}/api/runs/${encodeURIComponent(runId)}/computational-lab`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail || `Starting the Computational Lab failed with ${res.status}`);
    }
    return res.json();
  },
  promoteRun: async (runId: string, toStatus: "CANDIDATE" | "CHAMPION" | "ARCHIVED"): Promise<ArtifactView> => {
    const res = await fetch(
      `${BASE}/api/runs/${encodeURIComponent(runId)}/promote?to_status=${toStatus}`,
      { method: "POST", cache: "no-store" },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.detail || `Promote failed with ${res.status}`);
    }
    return res.json();
  },
};
