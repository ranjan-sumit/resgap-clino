import type { components } from "@/../../packages/contracts/typescript/api";

export type RunSummary = components["schemas"]["RunSummary"];
export type RunListResponse = components["schemas"]["RunListResponse"];
export type RunDetail = components["schemas"]["RunDetail"];
export type RunManifestView = components["schemas"]["RunManifestView"];
export type TraceStep = components["schemas"]["TraceStep"];
export type ProjectSummary = components["schemas"]["ProjectSummary"];
export type ProjectDashboard = components["schemas"]["ProjectDashboard"];
export type RunComparison = components["schemas"]["RunComparison"];
export type TechnicalLineage = components["schemas"]["TechnicalLineage"];
export type ScientificLineage = components["schemas"]["ScientificLineage"];
export type StatusChip = components["schemas"]["StatusChip"];
export type Measure = components["schemas"]["Measure"];
export type CountStat = components["schemas"]["CountStat"];
export type VersionField = components["schemas"]["VersionField"];

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

export const api = {
  health: () => get<components["schemas"]["HealthResponse"]>("/api/health"),
  listProjects: () => get<ProjectSummary[]>("/api/projects"),
  getDashboard: (projectId: string) =>
    get<ProjectDashboard>(`/api/projects/${encodeURIComponent(projectId)}/dashboard`),
  listRuns: (limit = 50) => get<RunListResponse>(`/api/runs?limit=${limit}`),
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
};
