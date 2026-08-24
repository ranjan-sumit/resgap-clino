import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // Clinova Phase 5: apps/web reads packages/branding/*.json (theme +
  // copy) directly from the filesystem and imports it into
  // tailwind.config.ts -- both live outside apps/web's own directory,
  // so file tracing needs to be rooted at the monorepo root.
  outputFileTracingRoot: path.join(__dirname, "../../"),
};

export default nextConfig;
