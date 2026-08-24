"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { StatusBadge } from "@/components/data/status-badge";
import { cn } from "@/lib/utils";
import type { ScientificLineage } from "@/lib/api";

type GapChainType = ScientificLineage["gaps"][number];

function RefList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral">
        {title} ({items.length})
      </p>
      {items.length === 0 ? (
        <p className="text-xs italic text-neutral">None</p>
      ) : (
        <ul className="space-y-1 text-xs text-clinova-deep">
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function GapChainCard({ chain }: { chain: GapChainType }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border border-border/60 bg-card shadow-card transition-shadow hover:shadow-card-hover">
      <CollapsibleTrigger className="flex w-full items-start justify-between gap-3 p-4 text-left">
        <div>
          <p className="font-medium text-clinova-deep">{chain.title}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge chip={chain.challenge} size="sm" />
            <span className="text-xs text-neutral">
              {chain.evidence.length} evidence · {chain.relationships.length} relationships ·{" "}
              {chain.entities.length} entities
            </span>
          </div>
          {chain.unresolved_note && <p className="mt-1.5 text-xs text-semantic-warning">{chain.unresolved_note}</p>}
        </div>
        <ChevronDown
          aria-hidden
          className={cn("mt-1 h-4 w-4 shrink-0 text-neutral transition-transform", open && "rotate-180")}
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-4 border-t border-border p-4">
        {chain.evidence_basis && <p className="text-xs text-neutral">{chain.evidence_basis}</p>}
        <div className="grid grid-cols-3 gap-4">
          <RefList
            title="Evidence"
            items={chain.evidence.map((e) => e.text || e.evidence_id || "Untitled evidence")}
          />
          <RefList
            title="Relationships"
            items={chain.relationships.map(
              (r) => `${r.source ?? "?"} — ${r.relation ?? "?"} — ${r.target ?? "?"}`,
            )}
          />
          <RefList title="Entities" items={chain.entities.map((e) => e.name ?? e.id ?? "Unnamed entity")} />
        </div>
        <RefList title="Proposals" items={chain.proposals.map((p) => p.title)} />
        {(chain.unresolved.evidence_ids_not_found.length > 0 ||
          chain.unresolved.relationship_ids_not_found.length > 0 ||
          chain.unresolved.entity_ids_not_found.length > 0) && (
          <div className="rounded-md bg-semantic-warning/5 p-3 text-xs text-neutral">
            <p className="mb-1 font-medium text-clinova-deep">Unresolved references</p>
            {chain.unresolved.evidence_ids_not_found.length > 0 && (
              <p>Evidence: {chain.unresolved.evidence_ids_not_found.join(", ")}</p>
            )}
            {chain.unresolved.relationship_ids_not_found.length > 0 && (
              <p>Relationships: {chain.unresolved.relationship_ids_not_found.join(", ")}</p>
            )}
            {chain.unresolved.entity_ids_not_found.length > 0 && (
              <p>Entities: {chain.unresolved.entity_ids_not_found.join(", ")}</p>
            )}
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
