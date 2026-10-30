# Audit 22h: the Docker image

## What was and was not checked
- **The image was not built or run.** The Docker daemon was not running on the machine used for this audit.
- The runtime dependency set was checked instead in a clean Python 3.11 virtual environment installed from the new hashed lock:
  84 application modules import, the Streamlit test harness renders the app, and `/_stcore/health` and `/healthz` both answer 200.
- Static tests (`tests/test_container_files.py`) check the Dockerfile, both compose files, `.dockerignore` and the lock.
- A build-and-run test exists in the same file. It builds the image, waits for the health check, confirms uid 10001, a read-only code
  directory and a writable `/data`. It is marked `slow` and skips itself when there is no Docker daemon. **Run it once on a machine with Docker
  before relying on the image.**

## Findings and what changed
| # | Finding | Change |
|---|---------|--------|
| 1 | `PyMuPDF>=1.24` let a fresh install pick 2.x, which pulls in an ONNX runtime and two more packages that were never tested here | Pinned `PyMuPDF>=1.24.0,<2`; a test fails if the lock contains the 2.x extras. Checking 2.x is part of PR-25 |
| 2 | The old compose file switched off cross-site request protection and CORS | Both are left on; a test fails if either is switched off anywhere |
| 3 | The container ran as root | Dedicated user (uid 10001); `USER` comes after every install step |
| 4 | The source tree was bind-mounted, so `.env` and data were visible inside the container | No source mount in the base file; data is in the named volume `data`; a separate dev override keeps the mount |
| 5 | The port was published on all interfaces | `127.0.0.1:8501:8501`; a reverse proxy with sign-in is documented as required |
| 6 | The build installed loose requirements, so two builds could differ | Installs from `requirements-runtime.lock` with `--require-hashes` (56 packages) |
| 7 | No read-only filesystem, capability drop, memory or process limits | `read_only`, `cap_drop: ALL`, `no-new-privileges`, `mem_limit 3g`, `pids_limit 256`, tmpfs for `/tmp` and `/home/app` |
| 8 | No health check, telemetry on | `HEALTHCHECK` on `/_stcore/health`; usage statistics off |
| 9 | Nothing kept secrets, data or tests out of the build context | New `.dockerignore` (`.env`, data, databases, tests, docs, evals, `.git`) with tests for both directions |
| 10 | `Dockerfile.api` and a host-specific compose copy were unused | Removed |
| 11 | The dev container upgraded the system packages and installed unpinned Streamlit | Now installs the pinned development requirements only |

## Still open
- The image has not been built here (see above).
- There is no sign-in, so the loopback port plus a reverse proxy is the only access control. Sign-in and roles are in PR-23.
- The page theme still loads fonts from Google Fonts, which fails where outbound access is blocked (PR-23).
- Image scanning (for example Trivy) and a software bill of materials are not set up.
- The base image is pinned by tag, not by digest.
