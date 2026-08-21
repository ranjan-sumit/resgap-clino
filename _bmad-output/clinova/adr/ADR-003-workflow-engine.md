# ADR-003: Workflow / orchestration engine — defer Temporal

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Enterprise Architect, DevOps/Platform Architect roles)

## Context

The brief specifies Temporal OSS for "durable orchestration" (§23). The existing pipeline (`app.py` sequencing `pipeline/*.py` filters) is a synchronous, in-process, single-session execution model with no current requirement for process-restart durability, human-in-the-loop pause/resume, or distributed worker fan-out.

## Decision

**Defer Temporal.** Retain the existing sequential in-process filter-chain execution model through at least Phase 4 (`03-system-architecture.md` AD-4). Introduce Temporal only when a concrete trigger exists — e.g., the Gap Challenger's multi-provider search fan-out needing durable retry-at-scale (possible Phase 3+ candidate trigger), or scheduled/background runs decoupled from an open browser session (possible Phase 4+ candidate trigger).

## Consequences

- No workflow-engine operational burden (learning curve, its own datastore, worker deployment) is paid before there is a real durability problem to solve.
- Run-level auditability/resumability in the interim is provided by the Run Manifest (`06-versioning-lineage-architecture.md`) recording stage-by-stage progress and quality-gate results — sufficient for the single-session, single-user scale this plan targets through Phase 4.
- Risk accepted: if a real durability need emerges earlier than expected (e.g., a long-running multi-provider search genuinely needs to survive a process crash), introducing Temporal mid-phase is a scoped, deliberate architecture change requiring its own ADR update — not a silent scope-creep addition.

## Alternatives considered

- **Adopt Temporal from Phase 1 (as literally specified):** rejected — no current trigger justifies the operational cost; directly contradicts the phase-gated infrastructure principle (`00-analysis-and-architecture-options.md` C5, C1).
- **A lighter task-queue (e.g., Celery/RQ) instead of Temporal:** not adopted now for the same reason — no current trigger. Recorded here as the more likely first step if a real async/background need appears before a full durable-workflow need does; revisit at that point rather than jumping straight to Temporal.
