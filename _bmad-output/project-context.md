---
project_name: 'Research_Gap_Analyzer'
user_name: 'Divya'
date: '2026-07-31'
sections_completed: ['technology_stack', 'language_framework_rules', 'critical_dont_miss_rules']
existing_patterns_found: 10
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- Python 3.11 (devcontainer: `mcr.microsoft.com/devcontainers/python:1-3.11-bookworm`)
- streamlit>=1.35.0 — entire UI lives in one file, `app.py` (~2400 lines)
- openai>=1.30.0 — SDK used against **NVIDIA NIM** (`https://integrate.api.nvidia.com/v1`), not OpenAI or Azure
- pdfplumber>=0.11.0, PyMuPDF>=1.24.0 — PDF parsing
- reportlab>=4.2.0 — proposal/PDF export
- numpy>=1.26.0, scipy>=1.12.0 — simulation engine math
- plotly>=5.20.0 — charts
- requests>=2.31.0 — Semantic Scholar / CrossRef / OpenAlex / PubMed / Unpaywall / arXiv API calls
- sqlite3 (stdlib) — run history persistence
- No package manager lockfile beyond `requirements.txt`; no `pyproject.toml`

## Critical Implementation Rules

### LLM Client Rules

- All pipeline LLM calls go through `utils/azure_client.py`'s `AzureOpenAIClient` (name is legacy — it is actually a NVIDIA NIM wrapper, kept "for backward compatibility"). Never assume Azure/OpenAI-direct behavior from that class name.
- `pipeline/llm_council.py` calls NVIDIA NIM directly via its own `_call_model()` with a fixed roster of 4 models (`openai/gpt-oss-20b`, `meta/llama-3.2-3b-instruct`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, `openai/gpt-oss-120b` as chair), each with individually tuned temperature/top_p/max_tokens/extra_body. Don't reuse one model's config for another; don't add a 5th agent without giving it its own tuned config block.
- All LLM calls stream (`stream=True`) and explicitly discard `reasoning_content` (thinking-model chain-of-thought) via a `_collect_stream`-style loop — never surface reasoning tokens to the UI or downstream JSON parsing.
- `chat()` never raises on API failure — after retries it returns a string like `"[API error after N attempt(s): ...]"` as if it were real content. Any new caller of `.chat()`/`.chat_json()` must check for this sentinel pattern before trusting the response, or it will silently propagate into wikis/gaps/proposals as garbage text.
- `chat_json()` appends a strict "ONLY valid JSON, no markdown fences" instruction. Parsing downstream still needs a fallback: strip code fences, regex-extract the outermost `{...}`/`[...]`, and trailing-comma cleanup — this exact 3-strategy fallback pattern is repeated in `wiki_compiler.py`, `llm_council.py` (`_robust_parse`), `reference_extractor.py` (`_safe_parse_list`), and `academic_search.py`. Reuse that pattern rather than inventing a new one.

### Domain Extension Rule

- New research domains are added **only** to the `DOMAINS` dict in `domain_config.py` (wiki_focus, entity_types, relationship_types, gap_priorities, proposal_framing, search_boost_terms). Never hardcode domain-specific prompt text inside a pipeline stage file — stages call `inject_domain_into_*` helpers instead.

### Paper Tiering Rule

- Respect the 3-tier corpus model (`pipeline/paper_manager.py`, `pipeline/reference_extractor.py`): Tier 1 = uploaded PDFs (full text), Tier 2 = cited refs enriched via academic APIs (abstract only), Tier 3 = refs that couldn't be enriched (title/year only). Never assume full text is available outside Tier 1 — code touching "papers" generically must branch on `tier`.

### Persistence Rule

- `utils/database.py` resolves its DB path relative to `__file__`, not cwd (`Path(__file__).parent.parent / "data"`). Each run is stored as ONE gzip-compressed JSON blob in `runs.results_gz`; the `papers` table only carries filename/title/tier for quick listing. There is currently no per-paper, per-reference, or per-wiki-page cache table — every run recompiles wikis and re-enriches references from scratch even for previously-seen papers (see architecture discussion below; flagged as a known gap, not yet fixed).

### External API Rules

- `pipeline/reference_extractor.py` and `pipeline/academic_search.py` call free, unauthenticated public APIs (Semantic Scholar, CrossRef, OpenAlex, PubMed, Unpaywall, arXiv) with small `time.sleep()` delays between calls to stay polite/within rate limits — do not remove these sleeps or parallelize these calls without adding real rate-limit handling.

### Bug-Fix Changelog Convention

- Preserve inline `# B<N> fix: <description>` comments when patching bugs (existing precedent: `azure_client.py`, `simulation_engine.py`, `graph_builder.py`, `multi_run.py`, `academic_search.py`). This is the project's lightweight in-code changelog — continue the numbering rather than dropping it.

### UI Convention

- All styling is inline CSS inside `app.py`'s single `st.markdown("""<style>...""")` block — there is no separate CSS/theme file. Reuse existing card classes (`stage-card`, `gap-card` with status-colored left border for open/partial/solved/pending, `proposal-card`) instead of inventing new ones.

### Not Established (do not assume)

- No test suite or test framework is present anywhere in the repo — don't assume pytest conventions or existing test coverage.
- No linter/formatter config (no `.flake8`, `pyproject.toml`, black/ruff/isort config) — match the surrounding file's existing style manually.
- No CI configuration found.
- Single `main` branch observed; no documented branch/commit message convention.
