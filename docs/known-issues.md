# Known issues and open decisions: release candidate

What is not done, not verified, or limited. Each item says what it affects and what to do about it.

## Not built yet
| Item | Effect | Waiting on |
|---|---|---|
| Storage adapter for cloud storage (Supabase or S3) | Data lives on the local disk or Docker volume only. On Streamlit Community Cloud the disk is wiped on redeploy. | Your choice of storage, or none |
| Sign-in and roles | The app has no users. Anyone who can reach the port can use it. Put a reverse proxy with TLS and sign-in in front, and have it set `RESGAP_ACTOR` per user. | Whether sign-in is needed, and the identity provider |
| Read-only share link | Results cannot be shared without exporting. | Same |
| Encryption at rest | The database and project files are not encrypted by the app. Use an encrypted disk or volume. | The regulation that applies |
| "Resume failed run" | A run that fails midway saves what exists, but cannot be continued; start a new run (cached stages are reused). | Not scheduled |

## Decisions pending
- **PyMuPDF licence (PR-25).** PyMuPDF is AGPL-3.0 or commercial. Private use creates no obligation; hosting it for other people or handing out the app does. Options are in `docs/pymupdf-licence-decision.md`.
- **PyMuPDF 2.x.** Held below 2 (`PyMuPDF>=1.24.0,<2`). Version 2 pulls in an ONNX runtime and two more packages and has not been tested here.
- **Regulation, internet access and model location.** Unanswered. They decide the remaining PR-23 work and which `RESGAP_EGRESS` mode to use.

## Not verified
- **The Docker image has never been built or run.** No Docker daemon was available. The dependency set was verified in a clean Python 3.11 environment, and the Dockerfile and compose files are checked by tests as text. `tests/test_container_files.py` has a build-and-run test that skips without Docker; run it once on a machine with Docker.
- **Only Gemini has been run live.** The real-model smoke test (`tests/test_real_smoke.py`) passed on Gemini: two small papers, 24 model calls, about 59,700 estimated tokens, 6 minutes 44 seconds on the free tier. NVIDIA, OpenAI, Groq and custom endpoints are covered by tests with fake clients only.
- **`RESGAP_EGRESS=none` has been tested with mocks, not with a firewall.** Confirm with a network capture before relying on it (checklist item).
- **The manual checklist (`docs/manual-checklist.md`) has not been done.** It needs a person and real papers.
- **Browser (Playwright) and slow suites** were not rerun for this candidate unless the release notes say so.

## Limits to know about
- **Audit log.** It is append-only and hash-chained, so editing or removing an entry is detected. Someone with direct file access can still replace the whole database, and the actor is a name taken from `RESGAP_ACTOR`, not a verified identity. Ship the CSV somewhere out of their reach if that matters.
- **Free-tier pace.** Gemini's free tier allows 5 requests a minute on the richer model, so a real run takes minutes, not seconds.
- **Reference matching depends on outside services.** OpenAlex limits keyless use to a small daily budget shared by everyone on a network, and Semantic Scholar's title search often refuses keyless requests. Set `OPENALEX_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY`; unresolved references are labelled as such. With `RESGAP_EGRESS=models` or `none` no reference is looked up.
- **Scanned PDFs** have no text layer; the Evidence Reader needs about 1,500 characters of body text and otherwise falls back to a path that has no quotes. There is no OCR.
- **`fitz` import.** The code still imports PyMuPDF as `fitz`, which PyMuPDF now reports as deprecated (a warning, not an error, on 1.x). Move to `import pymupdf` together with the PR-25 work.
- **Deleting with the default policy keeps a project's folder** in `_deleted/` so a mistake can be undone; set `RESGAP_ERASE_ON_DELETE=1` for permanent deletes.

## Housekeeping
- API keys were pasted into a chat during development. Rotate the OpenAlex, Gemini, Semantic Scholar and NVIDIA keys. `.env` is git-ignored and no key appears in tracked files or history (scanned for this release).
- The PR-23 part 1 commit also carries the earlier uncommitted run-planner and graph-screen work, because it shares `app.py` and could not be separated. That work has its own tests, which pass, but was not separately reviewed in this release.
- Nothing has been pushed to a remote.
