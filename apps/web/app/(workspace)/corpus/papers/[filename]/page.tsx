import type { Metadata } from "next";
import Link from "next/link";
import { PageHero } from "@/components/shell/page-hero";
import { ErrorState } from "@/components/data/error-state";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { api, ApiError, type PaperDetail } from "@/lib/api";

function ListCard({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">{title}</p>
      <ul className="list-disc space-y-1.5 pl-4 text-sm text-slate-800">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function TagCloud({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item, i) => (
          <span key={i} className="rounded bg-muted px-2 py-1 text-xs text-slate-800">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

async function loadPaper(projectId: string, filename: string) {
  return api.paper(projectId, filename);
}

async function resolveParams(params: Promise<{ filename: string }>) {
  const { filename } = await params;
  return decodeURIComponent(filename);
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ filename: string }>;
}): Promise<Metadata> {
  const filename = await resolveParams(params);
  try {
    const projects = await api.listProjects();
    if (projects.length === 0) return { title: "Paper" };
    const paper = await loadPaper(projects[0].project_id, filename);
    return { title: paper.title ?? filename };
  } catch {
    return { title: "Paper" };
  }
}

export default async function PaperDetailPage({ params }: { params: Promise<{ filename: string }> }) {
  const filename = await resolveParams(params);

  const projects = await api.listProjects();
  if (projects.length === 0) {
    return <ErrorState title="No projects yet" detail="No papers to show." retryHref="/corpus" />;
  }

  let paper: PaperDetail;
  try {
    paper = await loadPaper(projects[0].project_id, filename);
  } catch (err) {
    if (err instanceof ApiError) {
      return <ErrorState title="Paper not found" detail={err.message} retryHref="/corpus" />;
    }
    throw err;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <div>
        <Link href="/corpus" className="text-sm text-neutral hover:text-clinova-deep hover:underline">
          &larr; Corpus
        </Link>
      </div>

      <PageHero
        eyebrow={[paper.domain, paper.year].filter(Boolean).join(" · ") || "Research"}
        title={paper.title ?? paper.filename}
        description={
          paper.basis_run
            ? `From run "${paper.basis_run.name}" (${paper.basis_run.run_id.slice(0, 8)}) · ${paper.char_count.toLocaleString()} characters parsed`
            : `${paper.char_count.toLocaleString()} characters parsed`
        }
      />

      <div className="grid grid-cols-2 gap-4">
        <ListCard title="Contributions" items={paper.contributions} />
        <ListCard title="Key findings" items={paper.key_findings} />
        <ListCard title="Limitations" items={paper.limitations} />
        <ListCard title="Future work" items={paper.future_work} />
      </div>

      {(paper.methods.length > 0 || paper.datasets.length > 0 || paper.evaluated_on.length > 0) && (
        <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <div className="grid grid-cols-3 gap-6">
            <TagCloud title="Methods" items={paper.methods} />
            <TagCloud title="Datasets" items={paper.datasets} />
            <TagCloud title="Evaluated on" items={paper.evaluated_on} />
          </div>
        </section>
      )}

      <TagCloud title="Key concepts" items={paper.key_concepts} />

      {paper.comparison_gap && (
        <section className="rounded-lg border border-border/60 bg-card p-5 shadow-card">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-neutral">
            What this paper didn&apos;t compare against
          </p>
          <p className="text-sm text-slate-800">{paper.comparison_gap}</p>
        </section>
      )}

      {paper.tree_summary && (
        <Collapsible>
          <CollapsibleTrigger className="text-xs font-semibold uppercase tracking-wider text-clinova-deep hover:underline">
            Document outline
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3 rounded-lg border border-border/60 bg-card p-4 shadow-card">
            <pre className="whitespace-pre-wrap font-mono text-xs text-neutral">{paper.tree_summary}</pre>
          </CollapsibleContent>
        </Collapsible>
      )}

      {paper.sections.length > 0 && (
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
            Parsed sections ({paper.sections.length})
          </h2>
          <div className="space-y-2">
            {paper.sections.map((s, i) => (
              <Collapsible key={i} className="rounded-lg border border-border/60 bg-card shadow-card">
                <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-clinova-deep">
                  {s.heading}
                </CollapsibleTrigger>
                <CollapsibleContent className="border-t border-border/60 px-4 py-3">
                  <p className="whitespace-pre-wrap text-sm text-slate-800">{s.text}</p>
                </CollapsibleContent>
              </Collapsible>
            ))}
          </div>
        </section>
      )}

      {paper.tables.length > 0 && (
        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-neutral">
            Extracted tables ({paper.tables.length})
          </h2>
          <div className="space-y-3">
            {paper.tables.map((t, i) => (
              <div key={i} className="overflow-x-auto rounded-lg border border-border/60 bg-card p-4 shadow-card">
                <p className="mb-2 text-xs text-neutral">
                  Page {t.page} · {t.rows} rows &times; {t.cols} cols
                </p>
                <pre className="whitespace-pre font-mono text-xs text-slate-800">{t.content}</pre>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
