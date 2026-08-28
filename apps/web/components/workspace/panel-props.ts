/**
 * Every workspace tab is one of these (Clinova Phase 5, Slice 15).
 *
 * The panels exist so the tabbed workspace and the standalone routes render
 * the SAME markup from one definition. Copying each page's body into a tab
 * would have produced two versions of every screen that drift apart -- the
 * pattern that has already cost this project three separate duplicate-source
 * bugs (the title matcher, the Streamlit empty-state sentence, the basis-run
 * note). The route files are now thin wrappers around these.
 */
export interface PanelProps {
  projectId: string;
  /** Pins the panel to one run. Omitted = the project's most recent run. */
  runId?: string;
}
