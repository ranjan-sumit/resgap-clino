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
