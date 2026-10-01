import copyJson from "@/../../packages/branding/copy.json";

/**
 * Single source for user-facing workspace text (Clinova Phase 5, Epic 5.7).
 *
 * Deliberately a direct JSON import rather than going through
 * lib/branding.ts: that module is `server-only` (it reads the filesystem),
 * so a Client Component like the command palette or the New Run form could
 * never use it. Importing the JSON directly is bundler-resolved and works
 * in both Server and Client Components, which is what "reusable everywhere"
 * actually requires.
 *
 * Screens whose description genuinely varies per run (it names the basis
 * run and its short id) still build that sentence at render time -- pinning
 * it here would mean pretending a per-run fact is static copy.
 */
export const copy = copyJson;

export const common = copyJson.common;
export const screens = copyJson.screens;
export const shell = copyJson.shell;

export type ScreenKey = keyof typeof copyJson.screens;

/** Screen header text, so a page never restates its own eyebrow/title. */
export function screen(key: ScreenKey) {
  return copyJson.screens[key];
}
