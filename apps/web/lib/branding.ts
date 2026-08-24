import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { cache } from "react";

const BRANDING_DIR = path.join(process.cwd(), "../../packages/branding");

export interface BrandingTheme {
  product_name: string;
  tagline: string;
  engine_codename: string;
  colors: Record<string, string>;
  fonts: Record<string, string>;
}

export interface BrandingCopy {
  landing: {
    hero_headline: string;
    hero_supporting: string;
    primary_cta: string;
    secondary_cta: string;
    footer_trust_strip: string[];
  };
}

export interface Branding {
  theme: BrandingTheme;
  copy: BrandingCopy;
}

/**
 * Reads packages/branding/theme.json + copy.json directly from the
 * filesystem (Clinova Phase 5, NFR-1) -- a Server Component concern only,
 * never fetched client-side, so Landing can render fully static with no
 * duplicated strings. GET /api/config/branding exists as a parallel path
 * for any future client-only consumer.
 */
export const getBranding = cache(async (): Promise<Branding> => {
  const [themeRaw, copyRaw] = await Promise.all([
    readFile(path.join(BRANDING_DIR, "theme.json"), "utf-8"),
    readFile(path.join(BRANDING_DIR, "copy.json"), "utf-8"),
  ]);
  return { theme: JSON.parse(themeRaw), copy: JSON.parse(copyRaw) };
});
