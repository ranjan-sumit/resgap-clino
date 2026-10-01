import type { LucideIcon } from "lucide-react";
import {
  BookOpen, Database, FileCheck, FileText, Hash, Layers, Lightbulb, Network, Play, Share2, Sigma, Target, Unlink, Waypoints, Workflow,
} from "lucide-react";

// One tinted-well icon per stat key, so "Papers" looks like papers wherever
// the count appears (dashboard, run detail, council, graph). Unknown keys
// get a neutral hash rather than a wrong pictogram.
const STAT_ICONS: Record<string, LucideIcon> = {
  papers: FileText,
  references: BookOpen,
  evidence: FileCheck,
  gaps: Target,
  proposals: Lightbulb,
  entities: Waypoints,
  relationships: Network,
  communities: Share2,
  orphans: Unlink,
  bridges: Workflow,
  params: Sigma,
  derived: Sigma,
  t1: Layers,
  t2: Layers,
  n_runs: Play,
  corpus_confidence: Database,
  gap_confidence: Target,
};

export function statIcon(key: string): LucideIcon {
  return STAT_ICONS[key] ?? Hash;
}
