// Shared between the client TopBar (which writes it) and the server-only
// getSelectedProject() (which reads it). Kept in its own module because
// lib/project.ts imports next/headers, which cannot be pulled into a
// Client Component bundle.
export const PROJECT_COOKIE = "clinova_project";
