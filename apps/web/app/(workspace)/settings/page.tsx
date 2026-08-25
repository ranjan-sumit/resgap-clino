import type { Metadata } from "next";
import { PageHero } from "@/components/shell/page-hero";
import { getBranding } from "@/lib/branding";
import { api } from "@/lib/api";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const [{ theme }, health] = await Promise.all([getBranding(), api.health()]);

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <PageHero eyebrow="Settings" title="Settings" description="Read-only workspace configuration for this deployment." />

      <section className="rounded-lg border border-border/60 bg-card p-6 shadow-card">
        <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-neutral">System status</h2>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-xs uppercase tracking-wide text-neutral">API</p>
            <p className="mt-1 font-medium text-clinova-deep">{health.status}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-neutral">Database</p>
            <p className="mt-1 font-medium text-clinova-deep">{health.database}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-neutral">Git commit</p>
            <p className="mt-1 font-mono text-xs text-clinova-deep">
              {health.git_commit ? health.git_commit.slice(0, 12) : "Not recorded"}
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-border/60 bg-card p-6 shadow-card">
        <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-neutral">Branding</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-xs uppercase tracking-wide text-neutral">Product name</p>
            <p className="mt-1 font-medium text-clinova-deep">{theme.product_name}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-neutral">Tagline</p>
            <p className="mt-1 font-medium text-clinova-deep">{theme.tagline}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-neutral">Engine codename</p>
            <p className="mt-1 font-mono text-xs text-clinova-deep">{theme.engine_codename}</p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {Object.entries(theme.colors).map(([name, hex]) => (
            <div key={name} className="flex items-center gap-2 rounded-full border border-border/60 py-1 pl-1 pr-3 text-xs">
              <span className="h-5 w-5 rounded-full border border-border/60" style={{ background: hex }} />
              <span className="text-neutral">{name}</span>
              <span className="font-mono text-clinova-deep">{hex}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-dashed border-clinova-light/40 bg-white p-6 text-sm text-neutral shadow-card">
        Authentication and per-user preferences arrive in Phase 6 (governance) — this workspace is single-user and
        local for now, so there is nothing user-specific to configure here yet.
      </section>
    </div>
  );
}
