import { cookies } from "next/headers";
import { api, type ProjectSummary } from "@/lib/api";
import { PROJECT_COOKIE } from "@/lib/project-cookie";

export { PROJECT_COOKIE };

/**
 * Resolves the project every workspace screen should render.
 *
 * Before this existed, every page hardcoded `projects[0]` and the top bar's
 * project <Select> had no change handler at all -- so picking a different
 * project in the dropdown did literally nothing. This reads the selection
 * the TopBar writes (a cookie, so it survives navigation without rewriting
 * every internal link to carry a ?project= param), and falls back to the
 * first project when nothing is chosen or the stored id no longer exists.
 */
export async function getSelectedProject(): Promise<ProjectSummary | null> {
  const projects = await api.listProjects();
  if (projects.length === 0) return null;

  const stored = (await cookies()).get(PROJECT_COOKIE)?.value;
  return projects.find((p) => p.project_id === stored) ?? projects[0];
}
