import { Alert, AlertDescription } from "@/components/ui/alert";
import { StatusBadge } from "@/components/data/status-badge";
import type { TechnicalLineage } from "@/lib/api";

const COLUMN_LABELS: Record<number, string> = {
  0: "Corpus",
  1: "Papers & References",
  2: "Evidence",
  3: "Knowledge Graph",
  4: "Research Gaps",
  5: "Proposals",
  6: "Pipeline",
  99: "Other",
};

const NODE_WIDTH = 200;
const NODE_HEIGHT = 56;
const COL_GAP = 64;
const ROW_GAP = 20;
const HEADER_H = 28;
const PADDING = 24;

export function TechnicalDiagram({ lineage }: { lineage: TechnicalLineage }) {
  if (lineage.nodes.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-secondary/40 px-6 py-10 text-center text-sm text-neutral">
        No technical artifacts were recorded for this run.
      </p>
    );
  }

  const stageIndices = [...new Set(lineage.nodes.map((n) => n.stage_index))].sort((a, b) => a - b);
  const columns = new Map(stageIndices.map((si, i) => [si, i]));

  const rowsInColumn = new Map<number, number>();
  const positions = new Map<string, { x: number; y: number; col: number }>();
  for (const node of lineage.nodes) {
    const col = columns.get(node.stage_index)!;
    const row = rowsInColumn.get(node.stage_index) ?? 0;
    rowsInColumn.set(node.stage_index, row + 1);
    positions.set(node.artifact_id, {
      x: PADDING + col * (NODE_WIDTH + COL_GAP),
      y: PADDING + HEADER_H + row * (NODE_HEIGHT + ROW_GAP),
      col,
    });
  }

  const maxRows = Math.max(...[...rowsInColumn.values()]);
  const width = PADDING * 2 + stageIndices.length * NODE_WIDTH + (stageIndices.length - 1) * COL_GAP;
  const height = PADDING * 2 + HEADER_H + maxRows * (NODE_HEIGHT + ROW_GAP) - ROW_GAP;

  const center = (id: string) => {
    const p = positions.get(id);
    if (!p) return null;
    return { left: { x: p.x, y: p.y + NODE_HEIGHT / 2 }, right: { x: p.x + NODE_WIDTH, y: p.y + NODE_HEIGHT / 2 } };
  };

  return (
    <div className="space-y-4">
      {(lineage.orphan_note || lineage.truncated_after) && (
        <Alert className="border-semantic-warning/30 bg-semantic-warning/5">
          <AlertDescription className="text-clinova-deep">
            {lineage.orphan_note && (
              <p>
                {lineage.orphan_note} Orphans: {lineage.orphans.join(", ")}
              </p>
            )}
            {lineage.truncated_after && <p className="mt-1">Chain truncated at {lineage.truncated_after}</p>}
          </AlertDescription>
        </Alert>
      )}

      <div className="overflow-x-auto rounded-lg border border-border/60 bg-card p-4 shadow-card">
        <div className="relative" style={{ width, height }}>
          {stageIndices.map((si) => (
            <div
              key={si}
              className="absolute text-[11px] font-semibold uppercase tracking-wider text-neutral"
              style={{ left: PADDING + columns.get(si)! * (NODE_WIDTH + COL_GAP), top: PADDING, width: NODE_WIDTH }}
            >
              {COLUMN_LABELS[si] ?? COLUMN_LABELS[99]}
            </div>
          ))}

          <svg className="pointer-events-none absolute left-0 top-0" width={width} height={height}>
            <defs>
              <marker id="lineage-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" className="fill-neutral" />
              </marker>
            </defs>
            {lineage.edges.map((e, i) => {
              const from = center(e.parent);
              const to = center(e.child);
              if (!from || !to) return null;
              return (
                <line
                  key={`primary-${i}`}
                  x1={from.right.x}
                  y1={from.right.y}
                  x2={to.left.x - 6}
                  y2={to.left.y}
                  className="stroke-clinova-light"
                  strokeWidth={1.5}
                  markerEnd="url(#lineage-arrow)"
                />
              );
            })}
            {lineage.fan_in_edges.map((e, i) => {
              const from = center(e.parent);
              const to = center(e.child);
              if (!from || !to) return null;
              return (
                <line
                  key={`fanin-${i}`}
                  x1={from.right.x}
                  y1={from.right.y}
                  x2={to.left.x - 6}
                  y2={to.left.y}
                  className="stroke-neutral/50"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  markerEnd="url(#lineage-arrow)"
                />
              );
            })}
          </svg>

          {lineage.nodes.map((node) => {
            const p = positions.get(node.artifact_id)!;
            const isRoot = node.artifact_id === lineage.root;
            return (
              <div
                key={node.artifact_id}
                className={
                  "absolute flex flex-col justify-center gap-1 rounded-lg border bg-white px-3 py-2 shadow-card " +
                  (isRoot ? "border-clinova-blue shadow-glow-sm" : "border-border/60 shadow-card")
                }
                style={{ left: p.x, top: p.y, width: NODE_WIDTH, height: NODE_HEIGHT }}
              >
                <p className="truncate text-xs font-medium text-clinova-deep" title={node.label}>
                  {node.label}
                </p>
                <StatusBadge chip={node.status} size="sm" />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
