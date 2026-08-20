---
name: 'Clinova Research Intelligence Platform — Local Deployment Architecture'
type: architecture
altitude: capability
status: draft-for-review
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md', '03-system-architecture.md']
companions: ['10-phased-implementation-plan.md']
---

# Local Deployment Architecture — Clinova Research Intelligence Platform

## 1. Principle

Stand up only the infrastructure the current phase needs (`03-system-architecture.md` AD-2). Docker Compose profiles map **one-to-one with phases**, not with the brief's originally-proposed fixed core/research/security/observability grouping alone — that grouping is preserved as the *label taxonomy*, but membership and activation timing follow the phase gate.

## 2. Profile definitions

| Profile | Services | Activated at | Approx. added RAM |
|---|---|---|---|
| *(none — Phase 0-2)* | Existing dev container only (Python 3.11); GROBID and Docling run as lightweight local processes/containers introduced in Phase 1 without a full profile yet | Phase 0-2 | ~0.5-1 GB |
| `data` | GROBID (JVM service), Docling | Phase 1 | +1.5-2 GB |
| `core` | frontend (Streamlit through Phase 4 / Next.js from Phase 5), api (in-process through Phase 4 / FastAPI from Phase 5), postgres, minio, qdrant | Phase 3-4 (Qdrant at Phase 3; postgres/minio at Phase 4) | +2-3 GB |
| `research` | neo4j, research workers (if/when Temporal is ever triggered per AD-4) | Phase 3 (neo4j only; workers deferred) | +1-2 GB |
| `security` | keycloak, opa | Phase 6 — conditional, see `03-system-architecture.md` AD-6 | +1-1.5 GB |
| `observability` | langfuse, prometheus, grafana | Phase 7 | +1-1.5 GB |
| `experiments` | mlflow | Conditional — see `03-system-architecture.md` AD-5 | +0.3 GB |

**A developer never needs to run every profile simultaneously.** The heaviest realistic concurrent load through the end of Phase 4 is `data` + partial `core` (postgres, minio, qdrant) + `research` (neo4j) — roughly 5-7 GB, well short of running the brief's full stack (§23) all at once.

## 3. Developer onboarding flow (brief §49)

```text
1. git clone <repo>
2. cp .env.example .env          # NVIDIA API key, Semantic Scholar API key, local paths
3. docker compose --profile data up      # Phase 1+: GROBID, Docling
4. (Phase 3+) docker compose --profile core --profile research up
5. Run health checks (see §5)
6. Load seed data (see §4)
7. Open the application (Streamlit through Phase 4; Next.js from Phase 5)
```

Deliverables required to make this real (tracked as Phase 1 and Phase 5 epics respectively in `09-epics-and-stories.md`):
- `.env.example` with every required variable documented (never a real key committed)
- Seed data: a small sample project with 3-5 sample papers where licensing permits (e.g., open-access arXiv/PMC papers), matching the domain the existing `domain_config.py` already ships
- Health-check endpoints/scripts per service, checked before the app is declared "ready"
- Migration scripts: SQLite→Postgres (Phase 4), versioned and forward-only (no destructive down-migrations against research data)
- Developer documentation: `docs/` (this artifact set, kept current per-phase)

## 4. Seed data

A committed sample project (small corpus, 3-5 open-access papers in the existing domain) ships from Phase 1 onward specifically so the Corpus Quality Engine, reference resolution, and (from Phase 3) the Gap Challenger have something real to run against without requiring the developer to source their own papers first. This sample project is also the informal smoke test that the Clinova Benchmark's structural cases (§07) get promoted from once seeded.

## 5. Health checks

Each service in each profile exposes (or is wrapped with) a health-check the Compose file waits on before the dependent service starts — Postgres/Qdrant/Neo4j/MinIO all have standard health-check patterns; GROBID and Docling get a simple HTTP-ping wrapper since they don't ship one natively. No service is marked "up" in developer-facing tooling until its health check passes.

## 6. Cloud portability path (brief §25, §Phase 8 — not built in this pass)

Because every infrastructure-facing dependency sits behind a hexagonal port (`03-system-architecture.md` AD-2), the local Docker Compose profiles above become, unchanged in business logic, the service list that Phase 8's Kubernetes/Helm manifests and OpenTofu modules target. No research/business logic changes between local and cloud deployment — only the adapter implementation (e.g., MinIO → S3/Azure Blob/GCS behind `ObjectStore`) and the packaging (Compose → Helm) change.
