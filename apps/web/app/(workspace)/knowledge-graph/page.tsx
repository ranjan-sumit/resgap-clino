import type { Metadata } from "next";
import { redirect } from "next/navigation";

export const metadata: Metadata = { title: "Knowledge Graph" };

/**
 * Slice 15: this screen is now a tab of /workspace, so that reading it and
 * then reading a related one costs a tab click instead of a full navigation.
 * The route is kept as a redirect rather than deleted -- external links,
 * bookmarks, and the server-generated hrefs in search results and gap
 * cross-links all still point here, and a 404 would be a worse answer than
 * landing on the same content in its new home.
 */
export default async function KnowledgeGraphRedirect() {
  redirect("/workspace?tab=graph");
}
