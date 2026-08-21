---
name: 'Clinova Research Intelligence Platform — Versioning & Lineage Architecture'
type: architecture
altitude: capability
status: accepted
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md', '01-prd.md', '03-system-architecture.md']
companions: ['07-evaluation-architecture.md']
---

# Versioning & Lineage Architecture — Clinova Research Intelligence Platform

**Phase:** Introduced Phase 4 (Postgres-backed), though the *concepts* (content hashes, `stage_logic_version`) are already partially present in the baseline's SQLite cache tables and are extended, not replaced.

## 1. What gets versioned (brief §17, exhaustive list, binding)

Project, corpus, papers, extraction, references, evidence schema, embedding model, vector index, graph, graph builder, search strategy, search snapshot, prompt bundle, model bundle, agent definitions, pipeline, gap set, proposal set, report, evaluation benchmark.

**Binding rule:** every one of these is immutable once created. A change produces a new version; nothing scientifically load-bearing is overwritten in place. This generalizes the existing project's own `stage_logic_version`-bump-invalidates-cache convention (already used for `wiki_pages`/`parameters`/`references`/`gap_validations`) into a first-class product feature rather than an internal cache-invalidation mechanism only.

## 2. Research Artifact Registry (brief §18)

Postgres table, application-owned (not MLflow — see `03-system-architecture.md` AD-5):

```text
ResearchArtifact {
  artifact_id: string (content-addressed, SHA-256)
  artifact_type: enum(corpus, paper_extraction, reference_set, evidence_set, embedding_model,
                       vector_index, graph, graph_builder, search_strategy, search_snapshot,
                       prompt_bundle, model_bundle, agent_definitions, pipeline, gap_set,
                       proposal_set, report, evaluation_benchmark)
  artifact_version: string          # e.g. "corpus:v12"
  schema_version: string
  parent_artifact: string | null    # lineage edge — see §4
  project_id: string
  run_id: string | null
  created_at: timestamp
  content_hash: string
  storage_uri: string                # filesystem (Phase 4) / MinIO (Phase 4+)
  status: enum(EXPERIMENTAL, CANDIDATE, CHAMPION, ARCHIVED)
  metadata: jsonb
}
```

Example identifiers, exactly as illustrated in the brief: `corpus:v12`, `graph:v8`, `gapset:v19`, `proposalset:v14`, `report:v7`.

### Version status lifecycle

```text
EXPERIMENTAL → CANDIDATE → CHAMPION
                    ↓            ↓
                ARCHIVED ←───────┘
```

- **EXPERIMENTAL** — freshly produced by a run, not yet evaluated against the benchmark.
- **CANDIDATE** — passed the evaluation harness (`07-evaluation-architecture.md`) and is eligible for champion/challenger comparison.
- **CHAMPION** — currently the promoted, production-default version for its artifact type; promotion requires passing acceptance thresholds (§07), never a manual override alone.
- **ARCHIVED** — superseded by a later CHAMPION; retained (never deleted) for lineage/reproducibility.

## 3. Run Manifest (brief §19)

One immutable record per research run, itself a `ResearchArtifact` row (`artifact_type = pipeline` run instance) plus a dedicated `RunManifest` detail record:

```text
RunManifest {
  run_id: string
  project_id: string
  input_corpus_version: string
  pipeline_version: string
  git_commit: string
  parser_versions: { grobid: string, pymupdf: string, docling: string }
  reference_resolver_version: string
  embedding_model_version: string | null
  reranker_version: string | null
  graph_builder_version: string | null
  graph_version: string | null
  prompt_bundle_version: string
  model_bundle_version: string
  search_strategy_version: string
  academic_search_date: date
  search_providers: string[]
  output_artifacts: string[]          # ResearchArtifact.artifact_id references
  evaluation_metrics: jsonb            # per 07-evaluation-architecture.md
  warnings: string[]
  quality_gate_results: { corpus: enum(PASS,DEGRADED,FAIL), graph: enum(...), ... }
  run_duration_seconds: number
  token_usage: { total: int, by_stage: jsonb, by_agent: jsonb, by_model: jsonb }
}
```

This is the literal backing data for the Run Detail / Manifest UI screen (`02-ux-specification.md` §5, row 12) and the Runs list screen (row 11).

## 4. Lineage views (brief §43)

Two distinct, explicitly separate views — both queries over the same `ResearchArtifact.parent_artifact` graph, filtered by artifact-type family:

- **Technical lineage:** PDF → parser → evidence → embedding → graph → gap → proposal.
- **Scientific lineage:** paper → passage → claim → relationship → candidate gap → challenge → validated gap → proposal.

Every object in both views must be traceable end-to-end — this is the architectural requirement that Evidence Objects (`05-data-architecture.md` §8) and graph edges (§9) carry provenance references from the moment they're created, not retrofitted at the lineage-view layer.

## 5. Version Registry UI data contract

Backs `02-ux-specification.md` §5 row 16: for each artifact type, list of versions with `status`, `creator` (system/user), `date`, `parent`, `metrics` (pulled from the evaluation harness where applicable), and free-text `notes`.

## 6. Champion / Challenger (brief §20 — full detail in `07-evaluation-architecture.md`)

Promotion from `CANDIDATE` to `CHAMPION` is a `ResearchArtifact.status` transition, gated on the acceptance thresholds defined in `07-evaluation-architecture.md`, and is itself recorded as an event (who/what/when/why) — not a silent field update. The Compare UI screen's "Promote Candidate" action (`02-ux-specification.md` §5 row 13) is the only user-facing trigger for this transition; there is no separate backdoor path.
