import type { Metadata } from "next";
import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { PageHero } from "@/components/shell/page-hero";
import { ErrorState } from "@/components/data/error-state";
import { NewRunForm } from "@/components/runs/new-run-form";
import { api, ApiError } from "@/lib/api";

export const metadata: Metadata = { title: "New Run" };

export default async function NewRunPage() {
  let config;
  try {
    config = await api.newRunConfig();
  } catch (err) {
    if (err instanceof ApiError) {
      return <ErrorState title="Cannot start a run" detail={err.message} retryHref="/runs" />;
    }
    throw err;
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div>
        <Link href="/runs" className="text-sm text-neutral hover:text-clinova-deep hover:underline">
          &larr; All runs
        </Link>
      </div>

      <PageHero
        icon={FlaskConical}
        eyebrow="Engineering"
        title="New Run"
        description="Upload papers and run the full pipeline — parsing, evidence extraction, knowledge graph, gap detection, validation and proposals."
      />

      <NewRunForm config={config} />
    </div>
  );
}
