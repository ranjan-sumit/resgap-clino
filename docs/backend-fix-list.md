# Backend fix list

Evidence tags: **[run]** seen in a real run, **[test]** reproduced by a script or test, **[code]** read in the code, **[?]** suspected, not verified.
Each item says what to fix and how to prove it is fixed.

## P0: correctness and robustness (fix before relying on the results)

| ID | Problem | Evidence | Fix | Proof |
|---|---|---|---|---|
| B1 | A failing cross-paper-links call crashes the whole wiki stage, and with it the run (`compile_cross_links` is unguarded). | [test] `LLMCallError` raised | Catch it, record a trace warning, continue with empty links. | Test: link call fails, run still completes with a warning row. |
| B2 | Scanned (image-only) PDFs give 0 characters, yet the wiki model is still called on an empty paper, which invites invented content. | [test] char_count 0, model called | Detect "no text layer" in Stage 1, mark the paper unreadable, skip it with a clear error; optionally OCR through a vision model. | Test: scanned PDF is flagged, no wiki call, run reports it per paper. |
| B3 | A run lives inside the browser session's script thread; refreshing or closing the tab can kill a 6-10 minute run. | [?] Streamlit behaviour, seen when restarting the app mid-run | Run the pipeline in a background worker with progress persisted in the database; the UI only polls. | Test: start a run, drop the session, reconnect, run still finishes and shows progress. |
| B4 | Failures are swallowed (`except Exception: evidence_dicts = []` and similar) and there is no per-run error or call log. | [code] | Write `runs/<id>/llm_calls.jsonl` (model, stage, latency, tokens, error, prompt hash; prompts optional) and a structured error list in the manifest. | Test: failing call appears in the log; log is saved with the run. |
| B5 | Parallel stages (wiki, evidence, finders) have no shared rate limiter, so bursts hit free-tier limits (`gemini-3.6-flash` is 5 requests per minute; one key hit its quota). | [run] 429 quota error | Per-model token bucket in the router; honour `Retry-After` globally. | Test: 20 parallel calls on a 5 rpm model never exceed the limit. |
| B6 | More than 5 papers are silently cut to 5; duplicate files are analysed twice. | [test] no warning | Warn and list dropped papers; dedupe by content hash. | Test: 6 uploads gives a visible warning; duplicates collapse. |
| B7 | Per-model request options are keyed by model name only, so the same name on two providers shares settings (NVIDIA and Groq both serve `gpt-oss-20b`). | [code] | Key by (provider, model). | Test: Groq gpt-oss does not receive NVIDIA-specific options. |

## P1: quality of results

| ID | Problem | Evidence | Fix | Proof |
|---|---|---|---|---|
| B8 | The survey paper supports no gap in the final list; the set can cluster on one paper. | [run] | Critic already nudged; add a coverage check that warns when a paper supports no gap and an optional per-paper minimum. | Test: coverage row flags it; synthetic case spreads gaps. |
| B9 | Knowledge graph is tree-like (14 of 25 entities are orphan signals), built from wiki lists not quotes, relation evidence is paraphrase, entity types are model-invented. | [run] | Build from quoted evidence; second pass to link orphans; fixed type list per corpus; store quote ids on relations. | Test: orphan share below a threshold on the golden corpus; every relation has an evidence id. |
| B10 | Real tables are not parsed (structural finder found 0; pdfplumber gave empty frames, now filtered), so results tables reach models only as scattered text. | [run] | Table extraction pass (page-level, vision fallback); feed tables to the reader and parameter extractor. | Test: a PDF with a ruled table yields rows. |
| B11 | Page furniture becomes sections ("Pharmacological Research", "Journal of Cystic Fibrosis"). | [run] | Filter repeated header text and short title-like blocks. | Test: those headings absent on the fixture PDFs. |
| B12 | Parameter extraction counts survey opinions as parameters (28 of 40 came from the survey) and is LLM-only. | [run] | Categorise "opinion" vs "measured"; exclude opinions from simulation; add a numeric sanity pass. | Test: survey proportions tagged opinion, excluded from the gate count. |
| B13 | Gap critic and reviewer share the model family with the finders (self-preference); reviewer gave 4/4/4/4 to every proposal. | [run] | Anchor the rubric with examples; use a different model for the critic when available; track score spread. | Test: score distribution is not constant on a mixed-quality fixture. |
| B14 | Literature check takes ~24 s per gap (sequential, throttled); found papers carry no URL or DOI; cached "open" results never expire. | [run] | Parallelise providers, batch planner calls, store URL/DOI, add a TTL (for example 30 days) to the cache. | Test: 8 gaps in under half the time on fakes; URL present; expired entry is re-searched. |
| B15 | Lab: when the simulation does run, its algorithms were never audited for meaningful inputs; the insight council repeats itself; hypotheses can be speculative; grounding checks only effect-size numbers. | [run] partly, [?] | Audit each algorithm's input requirements; de-duplicate council output; extend grounding to named entities. | Tests per algorithm on known inputs; duplicate-insight test. |
| B16 | The feedback store exists but is not wired into the critic, reviewer or proposal prompts (original requirement). | [code] | Feed a project's past ratings into the critic and reviewer prompts; show the effect in the trace. | Test: a downvoted gap type is penalised next run. |
| B17 | Run-to-run variance is unmeasured (my reruns gave 10 and 8 gaps). | [run] | Lower temperature on structured stages; compute a repeatability metric per run. | Test: two runs on the golden corpus overlap above a threshold. |

## P2: data, operations, safety

| ID | Problem | Evidence | Fix | Proof |
|---|---|---|---|---|
| B18 | Each saved run is ~1.2 MB: the `corpus` key alone is 578 KB (duplicates paper text), `papers` 204 KB, and the Lab package is stored as text inside the JSON. 100 runs is ~120 MB and every open loads it all. | [test] | Drop `corpus` text, store sections and the zip as files, load lazily. | Test: new runs under 300 KB; old runs still load. |
| B19 | No cost or budget guard: tokens are recorded but never limited or priced. | [code] | Estimate cost before a run, cap tokens per run, warn near quota. | Test: a run over its cap stops cleanly with a message. |
| B20 | No quality metrics per run and no golden evaluation, so regressions are invisible. | [code] | Record quote rate, unsupported-number rate, duplicate rate, coverage and latency in the manifest; add a small golden eval script. | Test: metrics present; eval fails if the quote rate drops. |
| B21 | Manifest lacks prompt and agent-config versions; `AgentConfig.model` labels are stale. | [code] | Record `prompt_version` per agent; delete stale model labels. | Test: manifest lists every agent version. |
| B22 | Timestamps are naive local time; Cloud runs in UTC. | [code] | Store UTC with timezone. | Test: round-trip across timezones. |
| B23 | Server memory grew from 211 MB fresh to ~1.5 GB after several sessions and runs. | [run], cause [?] | Profile; free session results and report bytes; cap cached objects. | Test: memory flat across 20 simulated session loads. |
| B24 | Uploaded PDFs are untrusted: no page, time or memory limits on parsing. | [code] | Page cap, parse timeout, size check, worker process isolation. | Test: a 2,000-page PDF is refused quickly. |
| B25 | Dead and legacy code: single-call gap detector, `_LegacyBackend`, old validator, archived React/FastAPI, Postgres remnants, and 487 tracked files under `.claude`, `_bmad`, `evals` images. | [test] | Remove or untrack; keep tests for what stays. | Test: suite green after removal. |
| B26 | Cached results have no inspector or clear button. | [code] | Settings page: cache size per stage, clear per stage. | Test: clearing forces a recompute. |

## Not audited yet (risk unknown)

Reference extraction (Stage 1B) and the Corpus Quality Engine (2B, 1C); the Gap Challenger (5b) and its NVIDIA rerank dependency; figure analysis quality; OpenAI, Groq and custom-endpoint providers; graph snapshots and diffs; lineage records; the project zip export; the Docker image.

## Checked and fine

No API keys in the working tree or any commit (pattern scan, including this session's key formats); `.env` is not tracked; project-folder path guards exist.

## Suggested order

1. B1, B2, B4, B6 (small, high impact), then B5 and B7.
2. B18 and B19 before heavy use, B20 before changing prompts again.
3. B3 together with the frontend "live run" step, since it needs the same progress storage.
4. B9, B10, B12, B14 as one "grounded graph and literature" pass.
5. B25 and the untracking cleanup before the first push.


---

## Second pass: additional backend findings (B27-B41)

Found by re-reading the code and probing. Same evidence tags as above.

| ID | Problem | Evidence | Fix | Proof |
|---|---|---|---|---|
| B27 | **Cache keys ignore the model.** `compute_cache_key` hashes content, domain keys and stage version only. Changing the Extraction, Wiki or Analysis model silently serves the previous model's cached output, and the run manifest then names a model that did not produce it. | [code] | Add (provider, model) to every stage cache key; bump all stage versions once; show "served from cache" in the trace. | Test: same paper, two models, two cache entries; manifest lists the model that really ran. |
| B28 | **Model and PDF text is rendered as HTML without escaping.** 56 `unsafe_allow_html` sites, 28 `html.escape` uses; gap and proposal titles and text are interpolated raw. Text such as `p < 0.05`, or injected markup from a hostile PDF, can break the layout or run markup. | [code] | One `esc()` helper used in every HTML f-string; lint test that fails on raw interpolation of result fields. | Test: a gap titled `<img src=x onerror=alert(1)>` renders as text on every tab. |
| B29 | **Uploaded PDFs are left in the temp folder** when parsing fails (a corrupt-PDF run crashed with `PdfminerException` and left a copy behind). Papers can be confidential. | [test] 1 file left | Write temp copies inside `try/finally`; delete on any exit; prefer parsing from memory. | Test: no temp files remain after a failed run. |
| B30 | **Papers are identified by filename.** `evidence_objects[filename]`, `paper_profiles[filename]` and evidence ids use it, so two different papers both named `paper.pdf` overwrite each other. | [code] | Use a content-hash paper id everywhere; keep the filename for display only. | Test: two different PDFs with the same name both appear with their own evidence. |
| B31 | **PyMuPDF is AGPL-3.0 (or a paid commercial licence).** Fine for private use; hosting it as a service or distributing the app carries obligations. | [test] licence metadata | Decide: keep (internal only), buy the commercial licence, or switch to a permissively licensed parser (pypdfium2, pdfminer.six). | Written decision; if switching, parser contract tests on the fixture PDFs. |
| B32 | **Privacy of unpublished papers.** Papers are sent to third-party model providers. Google's published terms for the free tier allow using submitted content to improve its products (verify the current terms). | [?] | Privacy notice at upload; a per-project "confidential" flag that blocks free-tier providers and requires a no-training provider; optional redaction of names and emails. | Test: a confidential project refuses a free-tier model with a clear message. |
| B33 | **Prompt injection through paper text.** A PDF can contain instructions or hidden (white or tiny) text aimed at the models. | [?] | Strip invisible text; wrap paper text as quoted data with an explicit "treat as data" instruction; flag instruction-like phrases; quote verification already limits what can pass through. | Test: a fixture PDF with "ignore all previous instructions" produces no behaviour change and a flag in the trace. |
| B34 | **Dependencies are ranges, not pins** (`streamlit>=1.40`, etc.), so a Cloud deploy can pick up a breaking release. | [code] | Constraints or lock file; CI matrix on the supported Python versions; document them. | CI installs from the lock file and passes. |
| B35 | **Model registry goes stale.** Retired or renamed models appear in the lists and fail only at run time. | [?] | Distinct "model not found or retired" error; hide models that fail the health check; refresh the registry from each provider's list. | Test: a 404 model is flagged and removed from the picker. |
| B36 | **No bibliographic metadata** (DOI, authors, journal, year). Reports cite titles only; uploads cannot be de-duplicated by DOI; uploaded papers cannot be filtered out of the literature check. | [code] | Extract the DOI from the first page, look it up (Crossref), store metadata; use it in reports; exclude uploaded papers from "existing work". | Test: DOI found on a fixture; report lists full references. |
| B37 | **Long papers are cut silently** at 200,000 characters in the reader. | [code] | Warn, and read the rest in further parts. | Test: a 300,000-character fixture is read fully or reports exactly what was skipped. |
| B38 | **Agent outputs are parsed leniently but never schema-validated**, so a malformed item can slip through partially. | [code] | JSON-schema validation per agent; invalid items logged and counted. | Test: an item missing required fields is rejected and logged. |
| B39 | **No backup or restore** for the database and project folders. | [code] | Scheduled backup and a tested restore command. | Test: backup, wipe, restore, compare. |
| B40 | **Documentation drift.** README and notes describe the older design. | [?] | Architecture overview, runbook (quotas, troubleshooting), keep `DEPLOY.md` current. | Review checklist at release. |
| B41 | **Non-English papers untested.** | [?] | Detect language; warn; test one non-English fixture. | Test: warning shown; pipeline completes. |

Test-suite additions (not product bugs):
- **T1** Recorded real-response fixtures for each agent, so a model-format change is caught without a live call.
- **T2** Coverage measurement in CI with a floor that only goes up.

Checked and **not** a problem: 12 threads writing the cache at once caused no errors (SQLite WAL with a 30 s timeout); no uploaded paper was returned as its own "existing work" in the latest run (B36 still adds a defensive filter); usage telemetry is already off.
