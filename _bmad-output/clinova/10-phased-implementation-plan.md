---
name: 'Clinova Research Intelligence Platform — Phased Implementation Plan'
type: implementation-plan
status: draft-for-review
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md', '01-prd.md', '03-system-architecture.md', '09-epics-and-stories.md']
companions: ['09-epics-and-stories.md']
---

# Phased Implementation Plan — Clinova Research Intelligence Platform

This is the authoritative, resumable plan (brief §52). Each phase leaves the repository in a working, demoable state; no phase requires a big-bang cutover. **No phase begins until its entry trigger is concretely true** — this document exists specifically so a future session (or a different engineer) can resume without re-deriving the plan from scratch.

## Definition of Done (brief §54 — applies to every story in every phase)

A story is not done because the code runs. Done means:
- [ ] Functional tests pass (unit + integration, `pytest`)
- [ ] Relevant Clinova Benchmark regression case(s) pass, where applicable (Phase 1+)
- [ ] Data-quality tests pass, where applicable (Phase 1+)
- [ ] Versioning impact is recorded (does this change bump a `stage_logic_version`/artifact version? per `06-versioning-lineage-architecture.md`)
- [ ] Lineage/auditability is preserved (new artifact types register with the Artifact Registry once it exists, Phase 4+)
- [ ] Failure handling is explicit (no silent `except: pass`, no fallback treated as trusted — per ADR-007/Problem C)
- [ ] Observability considerations noted (even pre-Phase-7, is there a log line or metric a human would need later?)
- [ ] Documentation updated (this artifact set, kept current — not a one-time snapshot)
- [ ] Reproducibility considerations noted (does this touch anything in the determinism envelope, `04-ai-research-architecture.md` §6?)
- [ ] Token efficiency checked against `04-ai-research-architecture.md` §2's LLM-use discipline (code-review checklist item, `09-epics-and-stories.md` addendum)
- [ ] Security considerations noted (even pre-Phase-6: no secret committed, no unvalidated external input trusted)
- [ ] Migration considerations noted, where applicable (does this require a data migration? is it forward-only, non-destructive?)

## Phase gates

| Phase | Entry trigger (must be concretely true, not a calendar date) | Primary new infra | Exit criteria |
|---|---|---|---|
| **0 — Baseline** | Always true — this is the starting phase | None | Baseline report generated; Benchmark v1 seeded with 2+ real cases; Problems A-F measured against the real baseline (`09-epics-and-stories.md` Epic 0.1) |
| **1 — Data Foundation** | Phase 0 complete | GROBID, Docling (local services, `data` Compose profile) | Epics 1.1-1.4 done; Story 1.3.4's title-collision regression test passes; existing test suite (`tests/*`) still passes unmodified |
| **2 — Evidence Foundation** | Phase 1's quality gate (Epic 1.2) and reference resolution (Epic 1.3) pass their benchmark regression tests | None (SQLite/filesystem continue) | Evidence Objects populated for the sample project; graph/gap engine (Phase 3) has real Evidence Objects to consume, not wiki text |
| **3 — Reliable Research Intelligence** | Phase 2's Evidence Objects are populated and schema-valid for the sample project | Qdrant, Neo4j CE (`core`+`research` Compose profiles, partial) | Gap Challenger produces regression-tested statuses on Benchmark v1+; False Novelty Rate measured (not yet gated — gating starts Phase 4) |
| **4 — Versioned Platform** | Phase 3's Gap Challenger is benchmark-regression-tested; SQLite's single-blob-per-run limitation is the concrete blocker for cross-run comparison (already true today per `project-context.md`'s documented gap) | Postgres, MinIO (`core` Compose profile complete) | Run Manifest + Artifact Registry populated with real run history; champion/challenger promotion rule enforced with real thresholds tuned against Benchmark v2+ |
| **5 — Enterprise UI** | Phase 4's Run Manifest/Registry hold real (non-mock) data | Next.js, FastAPI | Full screen inventory (`02-ux-specification.md` §5) implemented against real contracts; Streamlit retired as the primary interface |
| **6 — Governance** *(conditional — no calendar trigger)* | A real second user needs access, OR a concrete compliance requirement is identified | Keycloak, OPA (`security` Compose profile) | Identity/policy/audit operational for the triggering need specifically — not built speculatively ahead of it |
| **7 — Observability** | Phase 5 UI is in regular use, generating enough real operational signal to be worth observing | Langfuse, OpenTelemetry, Prometheus, Grafana (`observability` Compose profile) | Dashboards reflect real run/token/latency/quality data |
| **8 — Portability** | A concrete cloud-deployment need exists (not built speculatively) | OpenTofu, Kubernetes/Helm | Local Compose services map 1:1 to cloud manifests with zero research-logic change |

## Rollback posture per phase

- **Phase 1-3:** all changes are additive to the existing pipeline (per `00-analysis-and-architecture-options.md` §3's retain/refactor table) — rollback is a standard git revert; no data migration exists yet to roll back.
- **Phase 4 (Postgres migration):** migration scripts are forward-only and non-destructive — the SQLite database is never deleted, only superseded, so rollback means reverting to reading from SQLite while the Postgres migration is fixed forward, not a destructive down-migration.
- **Phase 5 (Next.js UI):** Streamlit remains functional and deployable throughout Phase 5's development (parallel, not replaced-in-place) until the new UI is verified against real usage — rollback is switching the active interface, not restoring lost code.
- **Phase 6-8:** each is additive infrastructure with no impact on research-logic correctness if disabled — rollback is stopping the relevant Compose profile.

## Testing strategy by phase

| Phase | Testing approach |
|---|---|
| 0 | Manual verification of the baseline report; benchmark case review (human-in-the-loop, since these are the ground-truth cases themselves) |
| 1 | `pytest` unit tests per parser-reconciliation/resolution function; Benchmark v1 regression tests (title-collision, arXiv-mismatch cases) as integration tests; existing `tests/*` suite must continue passing unmodified (proves Phase 1 didn't regress Epic 1-3 baseline behavior) |
| 2 | Schema-validation tests for Evidence Objects; provenance-traceability tests (every claim traces to a real page/section) |
| 3 | Graph quality-scoring unit tests; Gap Challenger state-machine tests (every cell of the `04-ai-research-architecture.md` §5.2 decision table exercised); False Novelty Rate measured against Benchmark v2 (expanded with more known-closed-gap cases) |
| 4 | Migration correctness tests (SQLite→Postgres data integrity); Run Manifest completeness tests; champion/challenger harness tests using two intentionally-different toy pipeline versions before running it for real |
| 5 | Component tests (React Testing Library or equivalent, decided at Phase 5 kickoff); contract tests against Phase 1-4's real API shapes; manual UX walkthrough against `02-ux-specification.md`'s empty/loading/failure-state conventions |
| 6-8 | Infrastructure-as-code validation (`opentofu plan`/Helm lint); security-review pass at Phase 6 (secrets handling, policy correctness) before any real second-user rollout |

## Resuming this plan in a future session

If you are picking this plan up later: read `RESUME.md` first (index of what exists and current phase), then this document's phase-gate table to confirm the current phase's entry trigger is actually true before writing code, then the corresponding phase's epics in `09-epics-and-stories.md`. If a phase's stories aren't yet detailed (Phase 2+), use `bmad-create-story` against that phase's epic-level description here — do not skip straight to implementation without a story.
