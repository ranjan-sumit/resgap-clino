"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import theme from "@/../../packages/branding/theme.json";
import type { GraphView } from "@/lib/api";

type Entity = GraphView["entities"][number];
type Relationship = GraphView["relationships"][number];

interface SimNode {
  id: string;
  name: string;
  type: string;
  degree: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed: boolean;
}

const { clinova_cyan, clinova_light_blue, clinova_deep_blue, clinova_blue, success, warning, critical } =
  theme.colors;

const TYPE_COLOR: Record<string, string> = {
  concept: clinova_cyan, method: clinova_light_blue, dataset: success,
  metric: warning, problem: critical, domain: clinova_blue, model: clinova_deep_blue,
};

const WIDTH = 900;
const HEIGHT = 620;

// A real, self-contained force-directed layout -- no charting dependency,
// full control over brand styling. Nodes repel each other, edges pull
// their two endpoints together like springs, and everything drifts gently
// toward the center so the graph doesn't wander off-canvas. Runs as a
// short animated settle (a few seconds) so the structure visibly organizes
// itself, then freezes into static, still-draggable positions.
export function ForceGraph({ entities, relationships }: { entities: Entity[]; relationships: Relationship[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const nodesRef = useRef<Map<string, SimNode>>(new Map());
  const [, forceRender] = useState(0);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const dragRef = useRef<{ id: string } | null>(null);
  const panRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  const byId = useMemo(() => new Map(entities.map((e) => [e.id, e])), [entities]);
  const edges = useMemo(
    () => relationships.filter((r) => byId.has(r.source) && byId.has(r.target)),
    [relationships, byId],
  );
  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of edges) {
      (m.get(e.source) ?? m.set(e.source, new Set()).get(e.source)!).add(e.target);
      (m.get(e.target) ?? m.set(e.target, new Set()).get(e.target)!).add(e.source);
    }
    return m;
  }, [edges]);

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
        id: e.id, name: e.name, type: e.type, degree: degree.get(e.id) ?? 0,
        x: WIDTH / 2 + Math.cos(angle) * r, y: HEIGHT / 2 + Math.sin(angle) * r,
        vx: 0, vy: 0, fixed: false,
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

  return (
    <div className="overflow-hidden rounded-lg border border-border/60 bg-white shadow-card">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-[560px] w-full cursor-grab active:cursor-grabbing"
        onWheel={(e) => {
          e.preventDefault();
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
            if (n) { n.x = p.x; n.y = p.y; n.fixed = true; forceRender((v) => v + 1); }
          } else if (panRef.current) {
            const dx = e.clientX - panRef.current.startX;
            const dy = e.clientY - panRef.current.startY;
            setTransform((t) => ({ ...t, x: panRef.current!.origX + dx, y: panRef.current!.origY + dy }));
          }
        }}
        onMouseUp={() => { dragRef.current = null; panRef.current = null; }}
        onMouseLeave={() => { dragRef.current = null; panRef.current = null; }}
      >
        <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.k})`}>
          {edges.map((e, i) => {
            const a = nodesRef.current.get(e.source);
            const b = nodesRef.current.get(e.target);
            if (!a || !b) return null;
            const dimmed = activeId != null && a.id !== activeId && b.id !== activeId;
            return (
              <line
                key={i}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={theme.colors.neutral_gray}
                strokeWidth={1}
                opacity={dimmed ? 0.06 : 0.35}
              />
            );
          })}
          {nodes.map((n) => {
            const r = 5 + Math.min(n.degree, 10) * 1.6;
            const dimmed = activeId != null && n.id !== activeId && !activeNeighbors?.has(n.id);
            const isActive = n.id === activeId;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x} ${n.y})`}
                opacity={dimmed ? 0.25 : 1}
                className="cursor-pointer"
                onMouseEnter={() => setHoveredId(n.id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => setSelectedId((cur) => (cur === n.id ? null : n.id))}
                onMouseDown={(e) => { e.stopPropagation(); dragRef.current = { id: n.id }; }}
              >
                {isActive && <circle r={r + 5} fill="none" stroke={clinova_cyan} strokeWidth={2} opacity={0.5} />}
                <circle r={r} fill={TYPE_COLOR[n.type] ?? theme.colors.neutral_gray} stroke="white" strokeWidth={1.5} />
                {(isActive || n.degree >= 4) && (
                  <text
                    x={r + 5} y={4}
                    fontSize={11}
                    fill={clinova_deep_blue}
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    {n.name.length > 34 ? `${n.name.slice(0, 34)}…` : n.name}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border/60 px-4 py-2 text-xs text-neutral">
        {Object.entries(TYPE_COLOR).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: color }} />
            {type}
          </span>
        ))}
        <span className="ml-auto">Scroll to zoom · drag a node to pin it · drag background to pan</span>
      </div>
    </div>
  );
}
