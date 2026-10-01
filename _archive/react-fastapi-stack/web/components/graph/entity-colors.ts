import theme from "@/../../packages/branding/theme.json";

// Deliberately NOT inside force-graph.tsx: that file is "use client", and a
// function exported from a client module cannot be *called* by a Server
// Component (only rendered as a component or passed as a prop). The
// Knowledge Graph page is a Server Component and needs these exact colors
// for its entity list, so the palette lives in a plain shared module both
// sides can import.
const { clinova_cyan, clinova_light_blue, clinova_deep_blue, clinova_blue, success, warning, critical } =
  theme.colors;

export const ENTITY_TYPE_COLOR: Record<string, string> = {
  concept: clinova_cyan,
  method: clinova_light_blue,
  dataset: success,
  metric: warning,
  problem: critical,
  domain: clinova_blue,
  model: clinova_deep_blue,
};

export function entityColor(type: string): string {
  return ENTITY_TYPE_COLOR[type] ?? theme.colors.neutral_gray;
}
