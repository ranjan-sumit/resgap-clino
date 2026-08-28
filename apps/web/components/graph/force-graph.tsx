"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import theme from "@/../../packages/branding/theme.json";
import { entityColor } from "@/components/graph/entity-colors";
import type { GraphView } from "@/lib/api";

type Entity = GraphView["entities"][number];
type Relationship = GraphView["relationships"][number];

interface SimNode {
  id: string;
  name: string;
  type: string;
  importance: string;
  papers: string[];
  degree: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed: boolean;
}

const { clinova_cyan, clinova_deep_blue, clinova_blue } = theme.colors;

const WIDTH = 900;
const HEIGHT = 620;

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

// A real, self-contained force-directed layout -- no charting dependency,
// full control over brand styling. Nodes repel each other, edges pull their
// two endpoints together like springs, and everything drifts gently toward
// the center so the graph doesn't wander off-canvas. Runs as a short
// animated settle so the structure visibly organizes itself, then freezes
// into static, still-draggable positions.
export function ForceGraph({ entities, relationships }: { entities: Entity[]; relationships: Relationship[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const nodesRef = useRef<Map<string, SimNode>>(new Map());
  const [, forceRender] = useState(0);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showAllLabels, setShowAllLabels] = useState(false);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const dragRef = useRef<{ id: string; moved: boolean } | null>(null);
  const panRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  const byId = useMemo(() => new Map(entities.map((e) => [e.id, e])), [entities]);
  const edges = useMemo(
    () => relationships.filter((r) => byId.has(r.source) && byId.has(r.target)),
    [relationships, byId],
  );
  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of edges) {
      if (!m.has(e.source)) m.set(e.source, new Set());
      if (!m.has(e.target)) m.set(e.target, new Set());
      m.get(e.source)!.add(e.target);
      m.get(e.target)!.add(e.source);
    }
    return m;
  }, [edges]);

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of entities) counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [entities]);

  useEffect(() => {
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
    const map = new Map<string, SimNode>();
    entities.forEach((e, i) => {
      const angle = (i / Math.max(entities.length, 1)) * Math.PI * 2;
      const r = 180 + (i % 5) * 30;
      map.set(e.id, {
        id: e.id,
        name: e.name,
        type: e.type,
        importance: e.importance ?? "",
        papers: e.papers ?? [],
        degree: degree.get(e.id) ?? 0,
        x: WIDTH / 2 + Math.cos(angle) * r,
        y: HEIGHT / 2 + Math.sin(angle) * r,
        vx: 0,
        vy: 0,
        fixed: false,
      });
    });
    nodesRef.current = map;

    let frame = 0;
    let raf: number;
    const tick = () => {
      const nodes = [...nodesRef.current.values()];
      const cx = WIDTH / 2;
      const cy = HEIGHT / 2;

      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        if (a.fixed) continue;
        let fx = (cx - a.x) * 0.0025;
        let fy = (cy - a.y) * 0.0025;
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue;
          const b = nodes[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const distSq = Math.max(dx * dx + dy * dy, 25);
          const force = 2200 / distSq;
          fx += (dx / Math.sqrt(distSq)) * force;
          fy += (dy / Math.sqrt(distSq)) * force;
        }
        a.vx = (a.vx + fx) * 0.82;
        a.vy = (a.vy + fy) * 0.82;
      }
      for (const e of edges) {
        const a = nodesRef.current.get(e.source);
        const b = nodesRef.current.get(e.target);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const stretch = (dist - 110) * 0.02;
        const ux = dx / dist, uy = dy / dist;
        if (!a.fixed) { a.vx += ux * stretch; a.vy += uy * stretch; }
        if (!b.fixed) { b.vx -= ux * stretch; b.vy -= uy * stretch; }
      }
      for (const n of nodes) {
        if (n.fixed) continue;
        n.x = Math.min(WIDTH - 20, Math.max(20, n.x + n.vx));
        n.y = Math.min(HEIGHT - 20, Math.max(20, n.y + n.vy));
      }

      frame++;
      forceRender((v) => v + 1);
      if (frame < 220) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [entities, edges]);

  const toSvgPoint = (clientX: number, clientY: number) => {
    const svg = svgRef.current!;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * WIDTH;
    const y = ((clientY - rect.top) / rect.height) * HEIGHT;
    return { x: (x - transform.x) / transform.k, y: (y - transform.y) / transform.k };
  };

  const nodes = [...nodesRef.current.values()];
  const activeId = hoveredId ?? selectedId;
  const activeNeighbors = activeId ? neighbors.get(activeId) : null;
  // Labelling every neighbour of a 23-connection hub produces a solid block
  // of overlapping text. Past this many, the node keeps its own label and
  // the side panel carries the neighbour names instead (where they're
  // readable and clickable).
  const labelNeighbors = (activeNeighbors?.size ?? 0) <= 8;
  const selected = selectedId ? nodesRef.current.get(selectedId) : null;
  const selectedEdges = selectedId
    ? edges.filter((e) => e.source === selectedId || e.target === selectedId)
    : [];

  return (
    <div className="overflow-hidden rounded-lg border border-border/60 bg-card shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-2.5">
        <p className="text-xs text-neutral">
          Each dot is an entity extracted from your papers; each line is a stated relationship between two of
          them. Bigger dots are more connected.
        </p>
        <div className="flex shrink-0 items-center gap-3">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-neutral">
            <input
              type="checkbox"
              checked={showAllLabels}
              onChange={(e) => setShowAllLabels(e.target.checked)}
              className="h-3.5 w-3.5 accent-clinova-blue"
            />
            Label every node
          </label>
          {(selectedId || transform.k !== 1 || transform.x !== 0) && (
            <button
              onClick={() => { setSelectedId(null); setTransform({ x: 0, y: 0, k: 1 }); }}
              className="rounded border border-border/70 px-2 py-1 text-xs text-clinova-deep hover:bg-secondary"
            >
              Reset view
            </button>
          )}
        </div>
      </div>

      <div className="relative bg-white">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-[560px] w-full cursor-grab active:cursor-grabbing"
          onWheel={(e) => {
            const k = Math.min(3, Math.max(0.4, transform.k * (e.deltaY > 0 ? 0.9 : 1.1)));
            setTransform((t) => ({ ...t, k }));
          }}
          onMouseDown={(e) => {
            if (dragRef.current) return;
            panRef.current = { startX: e.clientX, startY: e.clientY, origX: transform.x, origY: transform.y };
          }}
          onMouseMove={(e) => {
            if (dragRef.current) {
              const p = toSvgPoint(e.clientX, e.clientY);
              const n = nodesRef.current.get(dragRef.current.id);
              if (n) {
                n.x = p.x; n.y = p.y; n.fixed = true;
                dragRef.current.moved = true;
                forceRender((v) => v + 1);
              }
            } else if (panRef.current) {
              const dx = e.clientX - panRef.current.startX;
              const dy = e.clientY - panRef.current.startY;
              setTransform((t) => ({ ...t, x: panRef.current!.origX + dx, y: panRef.current!.origY + dy }));
            }
          }}
          onMouseUp={() => { dragRef.current = null; panRef.current = null; }}
          onMouseLeave={() => { dragRef.current = null; panRef.current = null; setHoveredId(null); }}
        >
          <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
            {edges.map((e, i) => {
              const a = nodesRef.current.get(e.source);
              const b = nodesRef.current.get(e.target);
              if (!a || !b) return null;
              const touchesActive = activeId != null && (a.id === activeId || b.id === activeId);
              const dimmed = activeId != null && !touchesActive;
              return (
                <g key={i}>
                  <line
                    x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    stroke={touchesActive ? clinova_blue : theme.colors.neutral_gray}
                    strokeWidth={touchesActive ? 1.6 : 1}
                    opacity={dimmed ? 0.06 : touchesActive ? 0.7 : 0.3}
                  />
                  {/* Relation label only on highlighted edges, and only when
                      the active node has few enough of them to stay legible
                      -- a 23-edge hub would otherwise stack 23 copies of
                      "mentions" on top of each other. */}
                  {touchesActive && labelNeighbors && (
                    <text
                      x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 3}
                      fontSize={9}
                      textAnchor="middle"
                      fill={clinova_deep_blue}
                      opacity={0.75}
                      style={{ pointerEvents: "none" }}
                    >
                      {e.relation}
                    </text>
                  )}
                </g>
              );
            })}
            {nodes.map((n) => {
              const r = 5 + Math.min(n.degree, 10) * 1.6;
              const isActive = n.id === activeId;
              const isNeighbor = !!activeNeighbors?.has(n.id);
              const dimmed = activeId != null && !isActive && !isNeighbor;
              const labelled =
                showAllLabels ||
                isActive ||
                (isNeighbor && labelNeighbors) ||
                (activeId == null && n.degree >= 4);
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x} ${n.y})`}
                  opacity={dimmed ? 0.22 : 1}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredId(n.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onMouseDown={(e) => { e.stopPropagation(); dragRef.current = { id: n.id, moved: false }; }}
                  onClick={() => {
                    // Suppress the click that ends a drag, so repositioning
                    // a node doesn't also toggle its selection.
                    if (dragRef.current?.moved) return;
                    setSelectedId((cur) => (cur === n.id ? null : n.id));
                  }}
                >
                  {n.id === selectedId && (
                    <circle r={r + 6} fill="none" stroke={clinova_blue} strokeWidth={2} />
                  )}
                  {isActive && n.id !== selectedId && (
                    <circle r={r + 5} fill="none" stroke={clinova_cyan} strokeWidth={2} opacity={0.6} />
                  )}
                  <circle r={r} fill={entityColor(n.type)} stroke="white" strokeWidth={1.5} />
                  {labelled && (
                    <text
                      x={r + 5} y={4}
                      fontSize={11}
                      fill={clinova_deep_blue}
                      style={{ fontFamily: "var(--font-body)", pointerEvents: "none" }}
                    >
                      {truncate(n.name, isActive ? 46 : 26)}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>

        {selected && (
          <aside className="absolute right-3 top-3 max-h-[520px] w-72 overflow-y-auto rounded-lg border border-border/60 bg-white/95 p-4 shadow-card backdrop-blur-sm">
            <div className="flex items-start justify-between gap-2">
              <span
                className="mt-0.5 inline-flex shrink-0 items-center gap-1.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                style={{ background: `${entityColor(selected.type)}1a`, color: clinova_deep_blue }}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: entityColor(selected.type) }} />
                {selected.type}
              </span>
              <button
                onClick={() => setSelectedId(null)}
                className="text-xs text-neutral hover:text-clinova-deep"
                aria-label="Close entity details"
              >
                ✕
              </button>
            </div>

            <p className="mt-2 text-sm font-medium leading-snug text-slate-800">{selected.name}</p>

            <dl className="mt-3 space-y-1.5 border-t border-border/60 pt-3 text-xs">
              {selected.importance && (
                <div className="flex justify-between gap-2">
                  <dt className="text-neutral">Importance</dt>
                  <dd className="text-slate-800">{selected.importance}</dd>
                </div>
              )}
              <div className="flex justify-between gap-2">
                <dt className="text-neutral">Connections</dt>
                <dd className="text-slate-800">{selected.degree}</dd>
              </div>
            </dl>

            {selected.papers.length > 0 && (
              <div className="mt-3 border-t border-border/60 pt-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-neutral">
                  Appears in
                </p>
                <ul className="space-y-1 text-xs text-slate-800">
                  {selected.papers.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}

            {selectedEdges.length > 0 && (
              <div className="mt-3 border-t border-border/60 pt-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-neutral">
                  Relationships ({selectedEdges.length})
                </p>
                <ul className="space-y-1.5 text-xs">
                  {selectedEdges.slice(0, 25).map((e, i) => {
                    const outgoing = e.source === selected.id;
                    const otherId = outgoing ? e.target : e.source;
                    const other = nodesRef.current.get(otherId);
                    return (
                      <li key={i} className="leading-snug">
                        <span className="rounded bg-muted px-1 py-0.5 text-[10px] text-neutral">
                          {outgoing ? e.relation : `${e.relation} (in)`}
                        </span>{" "}
                        <button
                          onClick={() => setSelectedId(otherId)}
                          className="text-left text-clinova-deep hover:underline"
                        >
                          {other ? truncate(other.name, 40) : otherId}
                        </button>
                      </li>
                    );
                  })}
                </ul>
                {selectedEdges.length > 25 && (
                  <p className="mt-1 text-[10px] text-neutral">
                    +{selectedEdges.length - 25} more
                  </p>
                )}
              </div>
            )}
          </aside>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/60 px-4 py-2 text-xs text-neutral">
        {typeCounts.map(([type, count]) => (
          <span key={type} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: entityColor(type) }} />
            {type} <span className="text-neutral/60">({count})</span>
          </span>
        ))}
        <span className="ml-auto">Click a node for details · scroll to zoom · drag to move</span>
      </div>
    </div>
  );
}
