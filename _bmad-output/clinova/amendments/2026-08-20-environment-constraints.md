---
name: 'Amendment — Company-laptop environment constraints discovered at Phase 0 kickoff'
type: amendment
status: active
created: '2026-08-20'
amends: ['05-data-architecture.md', '08-local-deployment-architecture.md', '09-epics-and-stories.md']
---

# Amendment — Environment constraints discovered starting Phase 0

Recorded live during Phase 0 kickoff, per this project's own convention of dating findings rather than silently rewriting prior artifacts (matching the inherited baseline project's `deferred-work.md` style).

## What was found

- This machine (a company laptop) has **no local administrator rights** in this session (`whoami /groups` confirms not in `Administrators`; `Get-WindowsOptionalFeature` fails with "requires elevation").
- **WSL2 is not installed**, and installing it requires elevation this session doesn't have.
- **Docker Desktop cannot be installed** in this session as a result — it needs either the Hyper-V backend or WSL2, both gated behind admin rights.
- A `winget install Python.Python.3.11` attempt (non-elevated) was **silently cancelled by the installer itself** ("You cancelled the installation", exit 1602) — consistent with the same admin-rights restriction, since the python.org all-users installer triggers a UAC prompt that a non-interactive elevated session can't answer. A `--scope user` retry (which installs per-user, no elevation needed) was in progress when this amendment was written.
- **Java 11 (Microsoft OpenJDK, `jdk-11.0.16.101-hotspot`) is already installed** and on `PATH` — likely provisioned by IT for other tooling. This is materially useful: GROBID can run as a plain Java service via its Gradle build (`./gradlew run`), with no Docker dependency at all.

## Decisions (interim, until Docker access is resolved or confirmed unavailable long-term)

1. **Phase 1's multi-parser combination is temporarily two parsers, not three:** PyMuPDF (existing, pure Python) + **Docling** (pure pip-installable Python package, no Docker/JVM dependency — unaffected by this constraint). GROBID is **deferred**, not dropped — `05-data-architecture.md` §2's recommendation of GROBID+PyMuPDF+Docling stands as the target combination; only the sequencing changes.
2. **GROBID has a viable non-Docker path**, newly confirmed: build and run it directly via Gradle against the already-installed Java 11 (`./gradlew run`, no Docker/admin rights required — GROBID's Gradle build runs entirely in user space). This is **not attempted in this session** because it's a heavy, slow operation (cloning a large repo, a long first build, downloading pretrained citation-parsing models) that deserves a deliberate pass with disk-space/time awareness, not a side effect of unblocking Phase 0. Recorded here as the confirmed unblock path for whenever Phase 1's Epic 1.1 GROBID work is picked up.
3. **`08-local-deployment-architecture.md`'s `data` Compose profile assumption is revised for the interim:** Docling runs as a plain local Python dependency (no container). GROBID, when picked up, runs via Gradle directly rather than via the `data` Compose profile's Docker service — the Compose profile still applies once/if Docker access is later resolved (e.g., IT provisions it, or this work moves to a machine with admin rights), at which point this amendment is superseded, not deleted.
4. **Python 3.11 is being installed per-user** (`winget install --scope user`, no admin required) rather than via the devcontainer's all-users assumption — functionally equivalent for this project's purposes (a venv either way), just scoped to the current user profile instead of system-wide.

## What this does NOT change

- No architecture decision (ADR-001 through ADR-008) is affected — this is a local development-environment workaround, not a product architecture change.
- `05-data-architecture.md`'s target parser combination (GROBID + PyMuPDF + Docling) is unchanged as the eventual target; only *when* GROBID specifically is stood up is affected.
- Story 1.1.1 (`09-epics-and-stories.md`) is revised in place: its acceptance criteria now target the Gradle-based GROBID path instead of the Docker `data` profile, and are deferred to a dedicated pass rather than blocking the rest of Epic 1.1.

## Update, 2026-08-22 — full current list of what's blocked without Docker

Still true as of this date: no admin rights, no WSL2, Docker Desktop cannot be installed on this machine in this session. This is the consolidated list, across every phase touched so far, of what that concretely blocks — kept here as the single place to check rather than re-deriving it from scattered notes across `RESUME.md`/`09-epics-and-stories.md`. Update this list, don't fork a second one, as more phases get picked up.

**Resolved, 2026-08-22 — Neo4j replaced by ArcadeDB, not worked around:**
- ~~Neo4j CE (Phase 3, Epic 3.1 — Graph Persistence & Quality Scoring)~~ **The user decided against ever setting up Neo4j and asked for an open-source, no-Docker alternative instead of continuing to wait on Docker access.** [ArcadeDB](https://arcadedb.com) (Apache 2.0, actively maintained, speaks the same openCypher this project's docs already reference for Neo4j) runs as a plain local JVM process — no Docker, no admin rights, using the exact same "portable per-user install" pattern already established for Python 3.11 and planned for GROBID. Set up live this session: downloaded portable Eclipse Temurin JDK 21 (this machine only had Java 11, and ArcadeDB requires 21+) and the ArcadeDB 26.8.1 base distribution, both extracted to `C:\Users\Divya\tools\` with no installer. Started via `bin\server.bat` with `JAVA_OPTS=-Darcadedb.server.rootPassword=<password>` to skip the interactive first-run prompt (which hangs in a non-interactive session). Confirmed working end-to-end: HTTP API reachable, real vertex/edge writes, a real openCypher `MATCH` query returning the correct result.
- New `pipeline/graph_persistence.py` implements Epic 3.1's actual requirement (cross-run graph persistence -- comparing graphs across separate runs, which the existing in-memory single-run graph genuinely can't do) via ArcadeDB's HTTP API (`requests`, already a dependency -- no new Python package). Two real bugs found live and fixed: `DELETE VERTEX` needs a `FROM` keyword ArcadeDB's docs don't make obvious, and dereferencing an edge's connected-vertex property needs the `@`-prefixed `@out.field`/`@in.field` form -- the unprefixed form silently returns null instead of erroring. Both locked in with regression tests. Live-verified with two real saved runs from the same corpus family: saved both (96 and 61 entities), reconstructed one back byte-for-byte, and diffed them correctly (61 entities/relationships common to both, 34-35 unique to the larger 3-paper run -- exactly the expected shape given one run's corpus is a superset of the other's). Full detail in RESUME.md.
- **The server is a real, separate local process you now need to start manually before using this feature** (`JAVA_HOME=<path to the extracted JDK 21>; JAVA_OPTS=-Darcadedb.server.rootPassword=<your password>; bin\server.bat`, run from inside the extracted ArcadeDB distribution directory) -- nothing else in the pipeline depends on it, so everything else keeps working with it stopped. Not yet wired into `app.py`'s UI (module-first, same pattern as Gap Challenger and Repeatability Score before their own wiring passes) -- a natural next step if wanted.

**Still blocked, no alternative found yet:**
- **Qdrant (Phase 3, Epic 3.5 — EmbeddingProvider/RerankerProvider; also the remaining half of Epic 3.3 — Search Planner).** Needed for embedding-based retrieval and reranking in the search/challenge funnel. **No workaround exists** for this one — Epic 3.4's Gap Challenger (`pipeline/gap_challenger.py`) does real multi-provider search + LLM relevance judgment without it, but genuine embedding similarity/reranking has no non-Qdrant substitute in this codebase. `packages/contracts/search_provider.py`'s port is already shaped to accept a future embedding-backed provider without other code changes once this unblocks. Worth checking whether an ArcadeDB-style embedded/no-Docker open-source vector store exists too, next time this is picked up.

**Blocked, not yet actively needed (later phases, no current trigger):**
- **GROBID (Phase 1, Epic 1.1.1b).** Has a confirmed non-Docker path (Gradle build against the already-installed Java 11, see above) — genuinely unblocked, just not yet attempted (heavy first build, deliberately deferred pending a dedicated pass, not a hard blocker like the two above).
- **Postgres, MinIO (Phase 4, `core` Compose profile completion — Epic 4.1 Postgres Migration & Research Artifact Registry).** Not triggered yet — Phase 4's own entry trigger (SQLite's single-blob-per-run limitation becoming the concrete blocker for cross-run comparison) isn't clearly met until Phase 3's Gap Challenger is benchmark-regression-tested, which hasn't happened yet either.
- **Keycloak, OPA (Phase 6, `security` Compose profile — governance).** Explicitly conditional per `10-phased-implementation-plan.md` — no trigger (a real second user or compliance need) exists yet; not building this speculatively is a standing decision, not an oversight.
- **Langfuse, OpenTelemetry, Prometheus, Grafana (Phase 7, `observability` Compose profile).** Trigger is "Phase 5 UI in regular use, generating real operational signal" — nowhere close yet (still on the Streamlit interim UI).
- **Kubernetes/Helm, OpenTofu (Phase 8, portability).** Trigger is "a concrete cloud-deployment need exists" — none yet.

**Bottom line:** the two blockers that actually matter right now are Neo4j (Epic 3.1) and Qdrant (Epic 3.5/rest of 3.3) — everything else either has a working non-Docker path already in use, or genuinely has no trigger yet regardless of Docker access. Revisit this section when Docker/admin access is resolved (IT-provisioned, or moving to a different machine) or when a later phase's trigger condition becomes true.
