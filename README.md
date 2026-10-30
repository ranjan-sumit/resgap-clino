# ResGap: Research Gap Agent

Upload a set of research papers and the app reads them, quotes the evidence, builds a knowledge graph, finds gaps in the literature, checks
each gap against published work, and drafts research proposals. Every claim in a result links back to a quoted passage and page in a source
paper. An optional Computational Lab extracts parameters from the papers and runs simulations.

It is one Streamlit process and one SQLite file. No database server, no graph server.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # add at least one model key, e.g. GEMINI_API_KEY
streamlit run app.py                                   # http://localhost:8501
```

Create a project, add two or more PDFs, choose a domain, and run the analysis. A run takes a few minutes; the free Gemini tier is paced
to stay inside its request limit.

With Docker (read-only, non-root, data in a named volume): `docker compose up -d --build`. See [DEPLOY.md](DEPLOY.md).

## What you get

Overview, Evidence (verbatim quotes with page and section), Wiki (one page per paper), References (matched against Crossref, OpenAlex,
Semantic Scholar, PubMed and Europe PMC), Graph, Gaps (with a literature verdict: open, partial or solved), Proposals, Lab, Trace (what each
stage did and which model answered), and Export (HTML, PDF, Markdown, JSON, and a project zip with checksums).

Runs are saved in projects, can be compared, archived and deleted, and carry a lineage record that can be verified against the files.

## Configuration

Keys and the model for each job are set in the app (Settings) or in `.env`; only the model choice is saved, never a key. Deployment
settings (all optional, see [.env.example](.env.example)):

| Setting | Purpose |
|---|---|
| `RESGAP_DB_PATH`, `RESGAP_PROJECTS_DIR`, `RESGAP_BACKUP_DIR` | where data lives |
| `RESGAP_ALLOWED_PROVIDERS`, `RESGAP_ALLOWED_HOSTS` | which model providers and custom-endpoint hosts may be used |
| `RESGAP_EGRESS=open\|models\|none` | how far the app may reach: everything, model providers only, or nothing but an approved endpoint |
| `RESGAP_ERASE_ON_DELETE=1` | deletes are permanent |
| `RESGAP_ACTOR` | the name recorded in the audit log |
| `RESGAP_MAX_PDF_MB`, `RESGAP_MAX_PDF_PAGES`, `RESGAP_PARSE_TIMEOUT_S`, `RESGAP_ISOLATE_PARSER` | PDF limits |

Every run, delete, backup, export and settings change is recorded in an append-only, hash-chained audit log (Settings, Audit log).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q                                    # unit and app tests, no network, no model calls
python -m pytest tests/ui -q -m e2e -o addopts=""            # browser tests (needs: playwright install chromium)
python -m pytest tests -q -m slow -o addopts=""              # memory and load budgets
python -m pytest tests/test_real_smoke.py -m real -o addopts="" -s   # one real run; spends model tokens
```

## Documents

| | |
|---|---|
| [DEPLOY.md](DEPLOY.md) | running, Docker, controlled environments, backups |
| [docs/known-issues.md](docs/known-issues.md) | what is not done or not verified |
| [docs/manual-checklist.md](docs/manual-checklist.md) | the checks a person makes before a release |
| [docs/fix-sequence-and-regression-plan.md](docs/fix-sequence-and-regression-plan.md) | the work plan and regression matrix |
| `docs/audit-22*.md` | the audits of each area, with findings and fixes |
| [docs/pymupdf-licence-decision.md](docs/pymupdf-licence-decision.md) | an open licence decision (see known issues) |

## Licence note

PDF parsing uses PyMuPDF, which is licensed AGPL-3.0 or commercially. This is not yet resolved for distribution or public hosting; see
[docs/pymupdf-licence-decision.md](docs/pymupdf-licence-decision.md). Fonts in `static/fonts` are under the SIL Open Font License.
