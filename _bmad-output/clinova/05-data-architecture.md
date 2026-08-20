---
name: 'Clinova Research Intelligence Platform — Data Architecture'
type: architecture
altitude: capability
status: draft-for-review
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md', '01-prd.md', '03-system-architecture.md']
companions: ['04-ai-research-architecture.md', '06-versioning-lineage-architecture.md']
---

# Data Architecture — Clinova Research Intelligence Platform

## 1. Ingestion pipeline (brief §4)

```text
PDF → Multi-parser extraction → Extraction reconciliation → Completeness validation
    → Structured scientific representation → Reference resolution → Canonicalization
    → Relevance filtering → Evidence extraction → Quality gates → Trusted corpus
```

This is additive to, not a replacement of, the existing `pipeline/pdf_parser.py` / `pipeline/page_index.py` logic (per `00-analysis-and-architecture-options.md` §3): the existing parser becomes one of the multi-parser inputs to reconciliation.

## 2. Parser tool evaluation (brief §4, binding decision recorded as ADR-... within `03-system-architecture.md`'s scope)

| Tool | Medical/scientific PDF structure | References | Tables | Sections | Formulas | Metadata | Local RAM/startup cost | Accuracy (general) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **GROBID** | Strong — purpose-built for scholarly PDFs (TEI-XML output with structured sections/references/affiliations) | Strong — dedicated citation-parsing model, generally the best open-source option available | Moderate | Strong | Weak (not formula-aware) | Strong (title/authors/affiliations/DOI extraction is its core strength) | **Heavy** — JVM-based service, real RAM/startup cost (typically 1-2GB+ once warm), needs its own container | High on scholarly-format documents specifically | **Include, as the primary structural/reference parser** — its reference-parsing strength is the single highest-leverage fix for Problem B (contamination), which starts at bad reference parsing. |
| **PyMuPDF (existing)** | Moderate — general PDF text/layout extraction, not scholarly-structure-aware | Weak (raw text only, needs downstream regex/LLM parsing — the current source of Problem B risk) | Moderate (layout-based) | Weak (no semantic section detection) | Moderate (can extract embedded text near equations, not equation-aware) | Weak | **Light** — already in use, minimal cost | Good for raw text fidelity, poor for structure | **Retain as the second parser** — fast, already integrated, and a genuinely independent extraction method (different failure modes than GROBID) that reconciliation can cross-check against. |
| **Docling** | Strong — modern layout+table+structure model, actively maintained, table extraction is a specific strength GROBID lacks | Moderate (not citation-specialized like GROBID) | **Strong** — best table-extraction option evaluated | Strong | Moderate | Moderate | Moderate — Python-native, no separate JVM service, but model-weight download/load cost | High on complex layouts (multi-column, tables) | **Include, scoped specifically to table extraction** — closes GROBID's table-extraction gap without duplicating its reference-parsing role. Not used for reference parsing (GROBID already covers that better). |
| **Unstructured** | Moderate — general-purpose document parsing, not scholarly-specialized | Weak | Moderate | Moderate | Weak | Weak | Light-moderate | General-purpose, not best-in-class for any one of the scholarly-specific needs | **Exclude** — no capability here that GROBID+Docling+PyMuPDF don't already cover better; adding it would be complexity without a corresponding accuracy gain, which the brief explicitly warns against ("do not add packages merely because they are popular"). |

**Recommended minimum combination:** **GROBID (structure + references + metadata) + PyMuPDF (existing, fast raw-text cross-check) + Docling (tables specifically)**. This is three parsers, not four — Unstructured excluded on evidence, not by default. GROBID's JVM/RAM cost is real and is the reason it is introduced at **Phase 1** with its own Docker service (mapped in `08-local-deployment-architecture.md`'s `data` profile), not bundled into the Python process — consistent with the phase-gated infra rule in `03-system-architecture.md` AD-2.

**Open item carried to Phase 1 detailed design (already flagged in `01-prd.md` §9):** GROBID's concrete local resource cost needs a measured spike against this project's actual paper corpus size before final commitment — the above is a desk evaluation, not a benchmark result.

## 3. Extraction reconciliation (brief §5)

```text
GROBID extraction + PyMuPDF extraction + metadata provider (Semantic Scholar/CrossRef/etc., existing)
  + optional LLM recovery (only for fields where deterministic parsers disagree or both fail — per
    the LLM-use discipline in 04-ai-research-architecture.md §2)
  → Canonical paper representation
```

Every extracted field carries:

```text
ExtractedField {
  field_name: enum          # see §4 field list
  value: any
  source: enum(GROBID, PYMUPDF, DOCLING, METADATA_PROVIDER, LLM_RECOVERY)
  extraction_method: string
  page: int | null
  section: string | null
  confidence: enum(low, medium, high)
  extraction_version: string
}
```

When parsers disagree on a field, the reconciliation record keeps **all** candidate values with their sources (not just the winner) — this is the literal mechanism for "detect, measure, and prevent silent information loss" (Problem A): a disagreement is visible in the Paper Detail → Extraction tab (`02-ux-specification.md`), not silently resolved and hidden.

## 4. Scientific field completeness list (brief §5)

Tracked per paper for the Corpus Quality Engine (§6): title, authors, DOI, abstract, introduction, methodology, dataset/population, models/interventions, results, metrics, limitations, conclusion, future work, references, tables, figures.

## 5. Canonical paper & reference identity (brief §6, resolves Problem B — ADR-007)

**Resolution priority chain:**

```text
DOI → PMID → OpenAlex ID → Semantic Scholar ID → normalized(title + authors + year)
```

**Algorithm:**
1. Attempt resolution at each priority level in order; the first level that produces a confident match wins.
2. Normalized title+author+year (the fallback level) uses a stricter normalization than the existing project's `_norm` helper (lowercase+strip+truncate-to-60-chars, per the existing `reference_extractor.py`) — full-title normalization (no truncation) **plus** first-author-surname **plus** publication year, all three required to match, directly closing the exact collision risk the existing Story 2.3 code review already documented (a title-only match was judged insufficient there too).
3. Multiple provider records resolving to the same canonical identity are merged into one **Canonical Paper** record; each contributing provider's raw metadata is preserved separately as a `ProviderRecord` (not discarded) — so a later DOI-based re-resolution can be re-verified against the original provider data.
4. A canonical identity, once assigned, is immutable for that paper within a corpus version — a later run may create a new corpus version with a corrected identity (if evidence changes), but never silently rewrites history in place (consistent with `03-system-architecture.md`'s immutable-artifact rule).

## 6. Resolution status model (brief §3 Problem C, binding)

Every reference/paper in the corpus carries exactly one status:

| Status | Meaning | Transition rule |
|---|---|---|
| `VERIFIED` | Resolved via DOI/PMID with a confirming metadata-provider response | Entry status when priority-chain resolution succeeds at DOI/PMID level |
| `ACCEPTED` | Resolved via OpenAlex ID / Semantic Scholar ID, or normalized title+author+year with all three fields matching | Entry status for lower-priority-chain resolution |
| `QUARANTINED` | Fallback-only resolution (e.g., partial title match, single-field match) — held out of the trusted corpus, visible in the UI, not used for gap analysis by default | Entry status when no priority-chain level clears its match-confidence bar |
| `UNRESOLVED` | No resolution attempt succeeded at any level | Entry status when the reference can't be matched to any external identity |
| `REJECTED` | Explicitly determined not to belong (e.g., contradicts corpus-relevance filtering, or a user/reviewer marks it invalid) | Only reachable from `QUARANTINED` or `UNRESOLVED` via an explicit action (never an automatic transition) |

**Binding rule:** only `VERIFIED` and `ACCEPTED` references feed the trusted corpus used for gap analysis by default; `QUARANTINED`/`UNRESOLVED` are visible in the Data Quality / Corpus UI and can be manually promoted, never silently auto-promoted. This is the direct fix for Problem C ("fallback output must become a candidate requiring verification").

## 7. Corpus Quality Engine (brief §7)

Computed once per run, before gap analysis begins:

| Metric | Computation |
|---|---|
| Extraction completeness | % of §4's field list present with confidence ≥ medium, across the corpus |
| References detected / parsed / resolved / unresolved / quarantined | Funnel counts from §5-6 (this is the exact funnel rendered on the Data Quality UI screen, `02-ux-specification.md` §5 row 4) |
| Duplicate references merged | Count of provider records merged under one canonical identity (§5) |
| Domain relevance | % of corpus papers matching the active `domain_config` (existing mechanism, retained) |
| Metadata confidence | Aggregate confidence across `ExtractedField.confidence` values |
| DOI resolution rate | % of references resolved at the DOI priority level |
| Abstract availability | % of corpus papers with a non-empty abstract field |
| Search-provider coverage | % of configured `SearchProvider`s that responded successfully during corpus-level reference enrichment |

### Quality gate

```text
PASS      — extraction completeness ≥ threshold_pass AND DOI resolution rate ≥ threshold_pass
DEGRADED  — below PASS threshold but above threshold_fail; downstream stages run but every
            output surfaces the DEGRADED provenance and reduced confidence
FAIL      — below threshold_fail; downstream gap-analysis stages are blocked by default
```

Concrete threshold values are a Phase 1 implementation/tuning parameter (calibrated against the Clinova Benchmark, `07-evaluation-architecture.md`), not fixed here — the gate *mechanism* (block-by-default on `FAIL`, with an explicit logged override) is the binding architectural rule (PRD FR-3).

## 8. Evidence Objects (brief §8, resolves "wiki as sole source of truth")

```text
EvidenceObject {
  evidence_id: string (content-addressed)
  evidence_type: enum(ResearchQuestion, Problem, StudyDesign, DatasetPopulation,
                       InterventionModel, ComparatorBaseline, Method, Metric,
                       Result, Finding, Limitation, FutureWork, Claim)
  paper_id: canonical paper ID
  text: string
  provenance: { page: int, section: string, text_span: [start, end], extraction_version: string }
  confidence: enum(low, medium, high)
  evidence_object_version: string
}
```

The wiki-style synthesis (`pipeline/wiki_compiler.py`, retained per `00-analysis...` §3) continues to exist as a human-readable summary layer, but the Knowledge Graph and Gap Engine read **Evidence Objects only** — a graph edge or gap claim with no backing `evidence_id` is architecturally invalid (enforced by schema validation in `packages/research-schemas`, not just convention), directly satisfying PRD FR-8.

## 9. Knowledge graph data model (brief §9)

Node types: `Paper, Author, Disease, Population, Dataset, Model, Intervention, Method, Metric, Result, Claim, Limitation, ResearchGap`. Every relationship edge carries a `provenance: evidence_id[]` reference — no edge exists without at least one supporting Evidence Object (§8's rule, enforced at the graph-write layer). Graph persistence architecture (Neo4j CE + NetworkX) and versioning/quality-scoring are detailed in `03-system-architecture.md` (AD-2 port table) and `06-versioning-lineage-architecture.md` respectively.
