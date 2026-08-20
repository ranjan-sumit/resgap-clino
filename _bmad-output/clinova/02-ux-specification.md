---
name: 'Clinova Research Intelligence Platform — UX/Product Design Specification'
type: ux-spec
status: draft-for-review
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md', '01-prd.md']
companions: ['03-system-architecture.md', '09-epics-and-stories.md']
---

# UX / Product Design Specification — Clinova Research Intelligence Platform

**Scope note:** This specification defines the target Next.js/TypeScript UI (Phase 5 implementation). Through Phases 0-4, the existing Streamlit `app.py` remains the working interface, restyled toward this design system incrementally (a light, clinical theme change is already in progress in the baseline import) so the product is usable at every phase — see `00-analysis-and-architecture-options.md` §2, C6.

## 1. Design intent

The product must read as a premium pharmaceutical / medical research intelligence application — clean, clinical, calm, spacious, highly trustworthy, evidence-centric — never as a Streamlit demo, an AI chatbot, a student project, or a generic admin dashboard. Motion is used only where it clarifies a real state change (e.g., a pipeline stage completing), never decoratively.

## 2. Brand content model

Two distinct pieces of copy, not to be confused (see `00-analysis...` §2, C8):

| Element | Text | Where used |
|---|---|---|
| Product name | **Clinova Research Intelligence Platform** | Nav header, browser tab, exports, report cover page, footer |
| Tagline | **Evidence → Gaps → Hypotheses → Studies** | Nav header subline, footer, report cover page, PDF/HTML export header |
| Landing hero headline | **"Find the research nobody has done yet."** | Landing page only, once |
| Landing hero supporting copy | "Transform medical literature into evidence-backed research opportunities through structured discovery, adversarial validation and reproducible AI analysis." | Landing page only |
| Footer trust strip | "Evidence-driven · Reproducible · Versioned · Explainable" | Landing page footer |

All five live in the branding/content config layer (`03-system-architecture.md` §"Branding Layer"), not hardcoded in components, so the name/tagline/copy can change without a code change (PRD NFR-1).

## 3. Color system

Pfizer-inspired palette, used without any Pfizer logo, trademark, or affiliation claim (brief §26, binding).

| Token | Hex | Usage |
|---|---|---|
| `--clinova-blue` | `#0093D0` | Primary brand, links, primary buttons |
| `--clinova-deep-blue` | `#002596` | Headlines, emphasis, active nav |
| `--clinova-light-blue` | `#75D1E0` | Accents, chart secondary series |
| `--clinova-cyan` | `#00AEEF` | Interactive highlights |
| `--success` | `#00A950` | Verified/Open/Pass states only |
| `--warning` | `#F8971D` | Degraded/Partial/Quarantined states only |
| `--critical` | `#CC292B` | Rejected/Failed/Contested states only |
| `--neutral-gray` | `#616365` | Body text, secondary metadata |
| `--white` | `#FFFFFF` | Backgrounds |

**Rule:** blue and neutral tones dominate the interface; the three semantic colors (success/warning/critical) are reserved exclusively for status meaning — never used decoratively, never a "rainbow dashboard." Every status badge in every screen inventory below maps to exactly one of these three semantic colors plus neutral for "not yet evaluated" states.

## 4. Information architecture

### 4.1 Landing / login (unauthenticated)
Large light background split layout.
- **Left:** Product name, tagline, hero headline, supporting copy, primary CTA ("Start Research"), secondary CTA ("Open Workspace").
- **Right:** Abstract animated visualization: Papers → Evidence → Knowledge Graph → Research Gaps (network/particle style, not stock imagery, not a generic AI-robot illustration).
- **Footer:** trust strip (§2).

### 4.2 Application shell (authenticated)
**Left navigation**, grouped exactly as specified in brief §28:
- Logo / product name
- **Workspace:** Research, Projects
- **Research:** Corpus, Evidence, Knowledge Graph
- **Intelligence:** Research Gaps, Gap Challenger, Research Council, Proposals
- **Engineering:** Runs, Compare, Versions, Experiments, Lineage
- **Governance** *(Phase 6, conditionally hidden until governance is active — see PRD FR-33)*: Models, Prompts, Agents, Policies, Audit
- Settings

**Top bar:** project selector, corpus version, pipeline version, run status indicator, global search, notifications, profile.

## 5. Screen inventory

Each screen below states: purpose, key content, primary status/uncertainty language, and phase in which real backend data first exists for it (informs when Phase 5 implementation is meaningful vs. would be built against mocks — see `00-analysis...` C6).

| # | Screen | Purpose | Backend-ready phase |
|---|---|---|---|
| 1 | Project Dashboard | Executive overview: paper/reference/evidence/graph/gap counts; Research/Corpus/Evidence/Graph/Search-Coverage confidence; recent runs; top research opportunities; research activity timeline | Phase 4 (needs run history + confidence scoring across all engines) |
| 2 | Corpus | Uploaded papers, expanded references, quarantined/unresolved/duplicate references; filterable by source/year/relevance/resolution confidence/status/provider | Phase 1 |
| 3 | Paper Detail | Tabs: Overview, Evidence, Sections, References, Relationships, Extraction (parser-quality/disagreement view) | Phase 1-2 (Extraction tab needs Phase 1; Evidence/Relationships tabs need Phase 2-3) |
| 4 | Data Quality | Reference-resolution funnel (detected→parsed→resolved→relevant→quarantined→unresolved), duplicate rate, invalid-DOI rate, abstract coverage, fallback %, parser disagreement; overall `READY FOR RESEARCH` / `DEGRADED` / `BLOCKED` status with explicit reasons | Phase 1 |
| 5 | Knowledge Graph | Interactive graph: search/filter nodes by type/paper/confidence, trace paths, edge inspector (source paper, passage, relationship, confidence, extraction version), always-visible graph version, "Compare Graph Version" | Phase 3 |
| 6 | Research Gaps | List/cards: title, type, status, novelty confidence, evidence strength, search coverage, contradiction count, opportunity score | Phase 3 |
| 7 | Gap Detail | Header (title/status/confidence/type); "Why this may be a gap" / "Why this may NOT be a gap"; Literature Search summary; Evidence; History (status across versions); Actions (Challenge Again, Generate Proposal, Compare Version, Export Evidence) | Phase 3 |
| 8 | Gap Challenger | Visualized funnel: candidate gap → search strategy → N found → after dedup → after rerank → strongly relevant → contradicting → conclusion status; every stage inspectable | Phase 3 |
| 9 | Research Council | Per-agent (Gap Generator, Novelty Critic, Methodology Critic, Research Chair): summary, confidence, evidence cited, token usage; final chair recommendation (Proceed / Proceed with caution / Needs more evidence / Reject); no raw chain-of-thought shown | Phase 3-4 |
| 10 | Proposal | Explicit separation: evidence-backed facts / inferred direction / design recommendations / unverified assumptions / required validation; then research question, hypothesis, methodology, potential data, evaluation, risks, novelty, feasibility | Phase 1 (exists today, refactored per `00-analysis...`) |
| 11 | Runs | Table: run ID, created, project, corpus/pipeline/model/prompt/graph versions, status, duration, tokens, quality, outputs | Phase 4 |
| 12 | Run Detail / Manifest | Full immutable snapshot: input artifacts, code commit, configuration, models, prompts, search providers/date, parser/embedding/reranker versions, output artifacts, metrics, quality gates, failures, warnings, cost/token usage | Phase 4 |
| 13 | Compare | Side-by-side baseline vs. candidate across reference precision, extraction completeness, graph coverage, gap precision, **false novelty**, evidence recall, contradiction recall, consistency, latency, tokens; new/removed gaps, status/confidence/evidence changes with explanations; "Promote Candidate" gated on quality thresholds | Phase 4 |
| 14 | Research Time Machine | Selected gap's status evolution across corpus versions, with the specific new research that changed each status | Phase 4 (needs versioned corpus + gap history) |
| 15 | Lineage | Two views: Technical (PDF→parser→evidence→embedding→graph→gap→proposal) and Scientific (paper→passage→claim→relationship→candidate gap→challenge→validated gap→proposal) | Phase 4 |
| 16 | Version Registry | Versions for corpus/pipeline/models/prompts/agents/embeddings/graph/search-strategy/benchmark; status (`EXPERIMENTAL/CANDIDATE/CHAMPION/ARCHIVED`), creator, date, parent, metrics, notes | Phase 4 |
| 17 | Governance (Models/Prompts/Agents/Policies/Audit) | *Conditional, Phase 6* | Phase 6 |

## 6. Status & uncertainty language conventions

Never present a probabilistic or unresolved conclusion as certainty (PRD NFR-8). Concretely:

- Gap statuses always render as their literal state name (`OPEN`, `PARTIALLY_OPEN`, `CONTESTED`, `INSUFFICIENT_EVIDENCE`, etc.) with the semantic color (§3) plus a one-line plain-language explanation, never a bare color alone.
- Data-quality gates (`READY FOR RESEARCH` / `DEGRADED` / `BLOCKED`) always show the specific reason (e.g., "6 references unresolved, DOI resolution rate 71%"), not just the gate label.
- Confidence values are always shown with their source (e.g., "Evidence Strength: Medium — 3 of 5 supporting claims from Tier-1 papers"), never a bare percentage with no explanation available on demand.
- `INSUFFICIENT_EVIDENCE`/`SEARCH_PENDING` are visually and linguistically distinct from `OPEN` — this is the UI-level enforcement of PRD FR-12's core rule ("no search results" ≠ "gap is open").

## 7. Interaction conventions

- **Progressive disclosure:** dense technical detail (parser disagreement, raw search query strings, token counts) is available one click away, never on the primary card.
- **Empty states:** every list/table screen has a designed empty state with a clear next action (e.g., Corpus empty → "Upload your first paper"), not a blank table.
- **Loading states:** long-running stages (extraction, graph build, gap challenge) show real stage-by-stage progress (matching the run manifest's own stage list), not an indeterminate spinner.
- **Failure states:** a failed stage names what failed and why (LLM call failure vs. genuine empty result vs. quality-gate block — directly surfacing the P-C/P-D distinctions from the PRD), with a retry action where applicable.
- **Desktop-first:** the application shell (§4.2) is designed desktop-first per brief §28; responsive/mobile is out of scope for this planning pass.

## 8. Accessibility baseline

- Semantic color usage (§3) is never the sole signal — every status also carries text and, where iconography is used, a distinct shape/icon per status family (success/warning/critical/neutral).
- Color contrast for all text/background pairs meets WCAG AA at minimum against the white/neutral-gray palette.
- Full keyboard navigability for the left nav, top bar, and all table/list actions — detailed component-level accessibility acceptance criteria are written per-story in Phase 5's epics, not enumerated exhaustively here.

## 9. Open items for Phase 5 detailed design

- Exact component library / design-token implementation (e.g., Radix + Tailwind vs. another system) — a UX/UI Designer decision to make at Phase 5 kickoff, not before; deferred here to avoid a premature commitment matching `00-analysis...`'s speculative-abstraction caution.
- Knowledge Graph page's rendering library (e.g., Cytoscape.js, Sigma.js) needs a Phase 3 spike once real graph size/shape from Neo4j is known.
- Animated landing-page visualization (§4.1) needs a concrete asset/spec pass at Phase 5 kickoff — direction (network/particle abstraction) is fixed now, implementation is not.
