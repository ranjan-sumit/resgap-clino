"use client";

import { useEffect, useRef } from "react";

// Clinova Phase 5 Landing hero: an animated visualization that STATES
// the pipeline (Papers -> Evidence -> Knowledge Graph -> Research Gaps),
// not a generic decorative particle field or stock illustration
// (02-ux-specification.md §4.1). Deterministic node layout (seeded, not
// random) so screenshots taken during verification are reproducible.

const COLUMN_LABELS = ["Papers", "Evidence", "Knowledge Graph", "Research Gaps"];
const NODES_PER_COLUMN = 4;

// A tiny deterministic PRNG (mulberry32) -- no external dependency, and
// crucially NOT Math.random(), so the same seed always produces the
// same layout.
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Particle {
  columnIndex: number;
  fromNode: number;
  toNode: number;
  progress: number;
  speed: number;
}

export function HeroVisual() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const rand = mulberry32(20260824);
    const dpr = window.devicePixelRatio || 1;

    let width = 0;
    let height = 0;
    let raf = 0;

    const colors = {
      light: getComputedStyle(document.documentElement).getPropertyValue("--hero-light").trim() || "#85BDFB",
      cyan: getComputedStyle(document.documentElement).getPropertyValue("--hero-cyan").trim() || "#3D96F7",
      blue: getComputedStyle(document.documentElement).getPropertyValue("--hero-blue").trim() || "#85BDFB",
      deep: getComputedStyle(document.documentElement).getPropertyValue("--hero-deep").trim() || "#E8EAF2",
    };

    let nodePositions: { x: number; y: number }[][] = [];

    function layout() {
      const rect = canvas!.parentElement!.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas!.width = width * dpr;
      canvas!.height = height * dpr;
      canvas!.style.width = `${width}px`;
      canvas!.style.height = `${height}px`;
      ctx!.scale(dpr, dpr);

      const colGap = width / (COLUMN_LABELS.length + 1);
      nodePositions = COLUMN_LABELS.map((_, colIndex) => {
        const x = colGap * (colIndex + 1);
        return Array.from({ length: NODES_PER_COLUMN }, (_, i) => ({
          x: x + (rand() - 0.5) * 24,
          y: (height / (NODES_PER_COLUMN + 1)) * (i + 1) + (rand() - 0.5) * 20,
        }));
      });
    }

    layout();
    const resizeObserver = new ResizeObserver(() => layout());
    resizeObserver.observe(canvas.parentElement!);

    const particles: Particle[] = [];
    for (let col = 0; col < COLUMN_LABELS.length - 1; col++) {
      for (let i = 0; i < 5; i++) {
        particles.push({
          columnIndex: col,
          fromNode: Math.floor(rand() * NODES_PER_COLUMN),
          toNode: Math.floor(rand() * NODES_PER_COLUMN),
          progress: rand(),
          speed: 0.003 + rand() * 0.004,
        });
      }
    }

    function drawFrame() {
      ctx!.clearRect(0, 0, width, height);

      // Edges between adjacent columns
      ctx!.strokeStyle = colors.light;
      ctx!.globalAlpha = 0.35;
      ctx!.lineWidth = 1;
      for (let col = 0; col < nodePositions.length - 1; col++) {
        for (const a of nodePositions[col]) {
          for (const b of nodePositions[col + 1]) {
            ctx!.beginPath();
            ctx!.moveTo(a.x, a.y);
            const midX = (a.x + b.x) / 2;
            ctx!.bezierCurveTo(midX, a.y, midX, b.y, b.x, b.y);
            ctx!.stroke();
          }
        }
      }
      ctx!.globalAlpha = 1;

      // Flowing particles along the edges
      ctx!.fillStyle = colors.cyan;
      for (const p of particles) {
        const a = nodePositions[p.columnIndex][p.fromNode];
        const b = nodePositions[p.columnIndex + 1][p.toNode];
        const t = p.progress;
        const x = (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * ((a.x + b.x) / 2) + t * t * b.x;
        const y = (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * ((a.y + b.y) / 2) + t * t * b.y;
        ctx!.beginPath();
        ctx!.arc(x, y, 2, 0, Math.PI * 2);
        ctx!.fill();
        if (!prefersReducedMotion) {
          p.progress += p.speed;
          if (p.progress > 1) p.progress = 0;
        }
      }

      // Nodes
      nodePositions.forEach((col, colIndex) => {
        col.forEach((n) => {
          ctx!.beginPath();
          ctx!.arc(n.x, n.y, colIndex === nodePositions.length - 1 ? 5 : 4, 0, Math.PI * 2);
          ctx!.fillStyle = colIndex === nodePositions.length - 1 ? colors.deep : colors.blue;
          ctx!.fill();
        });
      });

      // Column labels
      ctx!.fillStyle = colors.deep;
      ctx!.font = "600 12px var(--font-mono, monospace)";
      ctx!.textAlign = "center";
      COLUMN_LABELS.forEach((label, i) => {
        const x = nodePositions[i]?.[0]?.x ?? 0;
        ctx!.fillText(label.toUpperCase(), x, height - 12);
      });

      if (!prefersReducedMotion) {
        raf = requestAnimationFrame(drawFrame);
      }
    }

    drawFrame();

    return () => {
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div className="relative h-full w-full bg-gradient-to-b from-chrome-deep to-chrome">
      <style>{`:root { --hero-light: #85BDFB; --hero-cyan: #3D96F7; --hero-blue: #85BDFB; --hero-deep: #E8EAF2; }`}</style>
      <canvas ref={canvasRef} className="h-full w-full" role="img" aria-label="Diagram showing the research pipeline flowing from Papers to Evidence to Knowledge Graph to Research Gaps" />
    </div>
  );
}
