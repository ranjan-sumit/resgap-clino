---
name: 'Docling resource measurement — Story 1.1.1a'
type: measurement
created: '2026-08-21'
---

# Docling resource measurement (real, not desk-estimated)

Measured against real papers from `Data-17072026/` (AuDHD_1.pdf ~1.5MB, AuDHD_2.pdf ~4.0MB) on this dev machine (Windows, CPU-only, no GPU).

| Run | Import | Init | Convert | Process RSS | Output |
|---|---|---|---|---|---|
| First run (AuDHD_1.pdf, cold — downloads layout model + RapidOCR weights, ~30MB) | 14.8s | 0.3s | 185.0s | (not captured — tracemalloc only, not real RSS) | 65,083 md chars, 5 tables |
| Second run (AuDHD_2.pdf, steady-state — models cached) | 14.1s | 0.1s | 86.0s | **1,142 MB** | 67,271 md chars, 4 tables |

**Revises `05-data-architecture.md` §2's original desk estimate ("Moderate — Python-native, no separate JVM service, but model-weight download/load cost") to "Heavy."** At ~1.1GB RSS and ~90s/paper, Docling is closer to GROBID's "Heavy" tier than the original estimate suggested — it avoids the JVM/Docker dependency (real win, given this machine's constraints — see `amendments/2026-08-20-environment-constraints.md`), but is not cheap to run.

**Design implication carried into Epic 1.1's reconciliation module:** Docling extraction must be cached by content hash (the same `content_hash:none:stage_logic_version` pattern already used for LLM calls, per AD-2/AD-3) — re-running it uncached on every pipeline run for unchanged papers is not viable at this measured cost. This is now a binding requirement on `pipeline/docling_parser.py`'s implementation, not optional.
