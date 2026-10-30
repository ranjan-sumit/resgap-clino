# Deployment

The app is a single Streamlit process plus one SQLite file. No database
server, no graph server, no GPU libraries.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate     # or .venv\Scripts\activate on Windows
pip install -r requirements.txt                        # ~0.7 GB installed
cp .env.example .env                                   # then add NVIDIA_API_KEY (or GEMINI_API_KEY)
streamlit run app.py
```

Run history, caches and saved knowledge graphs live in `data/run_history.db`
(override with `RESGAP_DB_PATH`). Delete the file to reset everything; it is
recreated on next start. The schema is applied from `migrations/*.sql`.

## Models

Each kind of LLM work can use its own provider and model, chosen in **Models for
this run** (right above **Run analysis**), with **Test models** to check them
before a run:

| Job | What it does |
|---|---|
| Extraction | parses/enriches references, extracts evidence (and Lab parameters) |
| Wiki & graph | compiles each paper's wiki page and the knowledge graph |
| Analysis | finds, validates and judges gaps; writes proposals |
| Council (seats 1-3, chair) | the Computational Lab's council |
| Fallback | takes over when a job's own model fails (a different provider is best) |

Providers: Gemini, NVIDIA, OpenAI, Groq, Qwen, and a **Custom endpoint** (any
OpenAI-compatible base URL). Set a key per provider in **API keys & endpoints**
or in the environment (`GEMINI_API_KEY`, `NVIDIA_API_KEY`, `OPENAI_API_KEY`,
`GROQ_API_KEY`, `CUSTOM_LLM_BASE_URL` + `CUSTOM_LLM_API_KEY`). Only the model
choice is saved (`data/model_settings.json`), never a key.

**Use recommended** picks from the keys you have, using measurements (see "Why
these recommendations?" in the panel). Key findings: gemini-3.5-flash-lite is
fast and has request headroom, so it runs the call-heavy jobs; gemini-3.6-flash
is richer but its free tier allows only 5 requests/minute, so it suits the
council; gemini-3.7-flash is ~20x slower and is not recommended. Each run
records which model did what, and every call the fallback had to take over, in
its manifest.

## How a run works

| Stage | What happens | Agents |
|---|---|---|
| 1 Parse | PyMuPDF reads each PDF into page-tagged text blocks and headings | — |
| 2 Wiki | one compiled page per paper (sees up to 60k characters, papers in parallel) | wiki compiler |
| 2C Evidence | each paper is read in parts of ~18k characters; every item carries a **verbatim quote** that is checked against the PDF text, with real page and section. Quotes that are not found, and statements whose numbers are not in the cited passage, are dropped. Also classifies the study type | **Evidence Reader** |
| 3 Graph | entities and relations; the vocabulary matches the corpus (the Healthcare-AI one only for ML or simulation studies) | graph builder |
| 4 Gaps | three finders work from the quoted evidence in parallel (authors' limitations, cross-paper synthesis, a per-paper methodology audit with a checklist for that study type); a critic scores novelty, importance and feasibility, merges duplicates and keeps the top ~12 | **Limitation Miner, Cross-Paper Synthesizer, Methodology Auditor, Methodology Critic** |
| 5 Literature | a planner writes short keyword queries per gap; Semantic Scholar + Europe PMC (arXiv only for ML corpora) are searched; an assessor says open / partial / solved naming the closest paper. A failed search is "unverified", never "open" | **Query Planner, Gap Assessor** |
| 6 Proposals | drafts, then a reviewer scores specificity, novelty, feasibility and impact and accepts, revises once, or rejects | **Proposal Reviewer** |
| Lab (optional) | parameters, hypotheses, simulation and an insight council. The simulation and model-selection council are **skipped** when the papers do not contain enough usable numbers | council agents |

Rule-based checks and graph-structure hints are kept as a separate "supplementary" list and are never validated or turned into proposals. Each run's trace and the **Paper coverage** panel show whether every paper made it through every stage.

`SEMANTIC_SCHOLAR_API_KEY` in `.env` (or the sidebar field) is used for the literature check: with a key a run's literature stage takes about 4 minutes, without one the free tier is much slower and often rate-limited.

## Projects

Analyses are grouped into **projects**. Creating one (sidebar, **New project**)
makes a folder next to the database, `data/projects/<name>-<id>/` (override the
location with `RESGAP_PROJECTS_DIR`):

```
project.json
papers/<hash>_<file>.pdf        uploaded papers, stored once per unique content
runs/<run_id>/results.json      the full results
              report.html       the report
              report.pdf
              manifest.json     model, options, and a file list
```

Everything is also recorded in the database (`projects`, `project_files`,
`run_files`), along with the user's feedback on gaps and runs (`feedback`).
The **Project** view lists a project's runs, compares any two, and has
**Download project (.zip)**, which bundles the folder plus a database export
of its runs and feedback. Runs from before projects existed sit in the
"Default project". `data/projects/` is gitignored: it holds user data.

`pipeline/feedback_context.py` formats a project's feedback for prompts
(`build_feedback_context(project_id, role="judge" | "agent" | "all")`). It is
not wired into any prompt yet.

## Docker (optional)

```bash
bash scripts/make_dotenv.sh        # or: powershell -File scripts/make_dotenv.ps1
# edit .env: add your key
docker compose up -d --build       # app on http://127.0.0.1:8501 (this machine only)
docker compose logs -f app
docker compose down                # keeps the data volume; add -v to delete it
```

The image installs from the hashed `requirements-runtime.lock`, runs as a non-root
user (uid 10001) on a read-only filesystem with no capabilities, and keeps the run
history, projects and backups in the named volume `data` (mounted at `/data`).
The source tree is not mounted. The port is published on loopback only: put a
reverse proxy with TLS and sign-in in front of it before anyone else connects,
because the app has no sign-in of its own.

Settings for a controlled deployment go in `.env`: `RESGAP_ALLOWED_PROVIDERS`,
`RESGAP_ALLOWED_HOSTS`, `RESGAP_ERASE_ON_DELETE`, `RESGAP_CONTACT_EMAIL`.
Back up the volume with the Settings, Backup tab or `scripts/backup.py`.

For development with the code mounted: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`
(restart the service after Python edits). Not for shared use.

After changing `requirements.txt`, regenerate both locks:
`uv pip compile requirements.txt --generate-hashes -o requirements-runtime.lock --python-version 3.11`
(and the same for `requirements.lock` with `requirements-dev.txt`).

## Controlled environments

Set these in `.env` (see `.env.example`). The Settings, Audit log tab shows what is in effect.

| Setting | Effect |
|---|---|
| `RESGAP_EGRESS=models` | Only model providers are reachable. Reference matching (Crossref, OpenAlex, Semantic Scholar, PubMed / Europe PMC, Unpaywall) and the literature check (arXiv) are switched off; references stay unresolved and the run says so. |
| `RESGAP_EGRESS=none` | Nothing leaves the network. The only model route is the custom endpoint, on this computer or on a host listed in `RESGAP_ALLOWED_HOSTS`. Any value other than `open`, `models` or `none` counts as `none`. |
| `RESGAP_ALLOWED_PROVIDERS`, `RESGAP_ALLOWED_HOSTS` | Which providers and custom-endpoint hosts may be used. |
| `RESGAP_ERASE_ON_DELETE=1` | Deletes are permanent. |
| `RESGAP_ACTOR` | The name written to the audit log. The app has no sign-in; a sign-in layer or reverse proxy in front of it should set this per user. |

Pages load no fonts or scripts from other sites: the fonts are served from `static/fonts` (SIL Open Font License, see `static/fonts/LICENSES.md`).

**Audit log.** Every run start and finish, delete, archive, backup, restore, export, project creation and model-assignment change is recorded
in the database with the time, the actor and the item, never with paper text, model output or keys. Entries cannot be edited or removed
through the app (the database refuses), each is chained to the one before by a hash, and the Audit log tab checks the whole chain. Someone
with direct file access can still replace the whole database, so ship the log (the CSV download) to a place they cannot reach if that matters.

## Streamlit Community Cloud

1. Push the repo to GitHub; create the app pointing at `app.py`. Cloud
   installs `requirements.txt` only.
2. In the app's **Secrets**, add `NVIDIA_API_KEY` and/or `GEMINI_API_KEY`
   (and optionally `SEMANTIC_SCHOLAR_API_KEY`).
3. **The Cloud disk is ephemeral**: `data/run_history.db` **and the project
   folders** are wiped when the app reboots or is redeployed, so run history,
   saved papers and reports there last only until then. Use **Download project
   (.zip)** in the Project view to keep a project.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -q                   # each DB test gets its own throwaway SQLite file
```

## Troubleshooting

- **`database is locked`** — another process holds the file open for writing;
  SQLite allows one writer at a time. Close the other session or point
  `RESGAP_DB_PATH` elsewhere.
- **LLM errors in runs** — key missing/invalid: check `NVIDIA_API_KEY` /
  `GEMINI_API_KEY` in `.env`, or paste it in the Streamlit sidebar.
