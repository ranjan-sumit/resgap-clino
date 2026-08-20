# Rubric Walker Review — ARCHITECTURE-SPINE.md (ResGap Pipeline Soundness & Caching Architecture)

**Reviewer role:** rubric walker (BMAD architecture-spine Reviewer Gate)
**Artifact reviewed:** `architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md`
**Method:** spine read in full; cross-checked every AD's binding and rule against the actual source files it names (`app.py`, `pipeline/*.py`, `utils/*.py`, `requirements.txt`) and against the grounding research doc.

## Verdict

**REQUEST CHANGES.** The spine is well-organized and mostly ratifies the real codebase, but it (a) silently drops one of the six confirmed defects from scope, (b) contains one AD (AD-1) whose "ratified, already-the-case" claim is contradicted by three existing imports in the actual codebase, (c) has two ADs (AD-4, AD-5, AD-6) whose Rules are scoped too narrowly to actually close the defect they claim to prevent, once checked against the real code paths, and (d) is silent on cache growth/retention — a new operational concern this spine itself introduces — under a Deferred entry that only addresses concurrency, not size.

---

## Findings

### 1. [HIGH] A confirmed defect (malformed arXiv query) is dropped from scope with no trace — not fixed, not deferred

The grounding research doc confirms six defects. The spine's own `scope` field maps four of them to ADs:
- caching → AD-2/AD-3 (defect #6)
- resilient academic-API integration → AD-5 (defect #3, the Semantic Scholar 429)
- Result-type at LLM boundary → AD-4 (defect #5, graph_builder conflation)
- confidence-gated pooling → AD-6 (defects #1/#2)

Defect #4 — the malformed arXiv query (`pipeline/academic_search.py:46`, live-reproduced: unquoted multi-word `all:` field is parsed as OR-of-words, returning topically unrelated papers) — appears in **neither an AD nor the Deferred section**. Verified in the actual code:

```python
params = {
    "search_query": f"all:{urllib.parse.quote(query)}",
    ...
}
```

`urllib.parse.quote` only percent-encodes spaces; it does not wrap the phrase in the quoting arXiv's parser needs to treat it as a phrase rather than an OR of terms. AD-5's rule (retry-with-backoff + API key) does nothing for this — the arXiv call in this bug returns HTTP 200 with wrong results, so there is no failure to retry. This is a pure query-construction bug, orthogonal to resilience.

This directly violates the checklist's "fixes the real divergence points... and misses none." If this was intentionally out of scope, the spine needed to say so in Deferred with a reason; as written it reads as an oversight, and a future implementer reading this spine has no signal that the bug (which the research doc says is one of two *live-reproduced* root causes of the sample report's "no relevant papers found" results) still needs fixing.

### 2. [HIGH] AD-1's "already the case" ratification claim is contradicted by the actual codebase

AD-1's Rule: *"Filters do not import other filters directly — they only receive/return dicts through `app.py`'s orchestration."* Tagged `[ADOPTED] — already the case in the existing codebase; this fixes it as a rule rather than an accident.`

This is false as stated. Grepping the actual repo:

```
pipeline/multi_run.py:16:    from pipeline.llm_council import council_synthesise_insights
pipeline/wiki_compiler.py:8: from pipeline.pdf_parser import get_smart_excerpt
pipeline/wiki_compiler.py:9: from pipeline.page_index import tree_to_summary
```

Three existing filter→filter imports exist today, contradicting "already the case." This matters for the brownfield-ratification check specifically: a spine that ratifies a pattern the codebase doesn't actually follow isn't ratifying, it's silently proposing a refactor while claiming it's free. Either:
- AD-1's rule needs loosening to match reality (e.g., permit intra-`pipeline` helper imports for shared parsing/summarization utilities, and reserve the "filters don't call filters" rule for the actual orchestration-stage functions `app.py` calls), or
- the spine needs to acknowledge this is a real, currently-violated invariant and that enforcing it requires touching `multi_run.py`/`wiki_compiler.py` — work that isn't in the stated "four fixes" scope and isn't in the Structural Seed's file list.

As written, AD-1 is not enforceable without an unacknowledged scope expansion.

### 3. [HIGH] AD-5's Rule doesn't fix the exact failure mode it names, because the bug isn't an exception

AD-5 prevents: *"a transient rate-limit (429)... being silently reported as 'no relevant papers found'"* and its Rule is: *"every such call is wrapped in `tenacity` retry with exponential backoff + jitter before falling back to an empty result."*

Checked against the actual code (`academic_search.py::_search_semantic_scholar`, and the analogous lookup functions in `reference_extractor.py`, e.g. `_ss_by_doi`, `_ss_by_arxiv`, `_crossref_by_doi`):

```python
try:
    resp = requests.get(SEMANTIC_SCHOLAR_BASE, params=params, timeout=10)
    if resp.status_code == 200:
        ...
        return results
except Exception:
    pass
return []
```

A 429 response does **not** raise an exception here — `requests.get` doesn't raise on non-2xx status unless `.raise_for_status()` is called, which this code never does. The `if resp.status_code == 200` simply fails, falls out of the `try`, and hits `return []`. `tenacity`'s `@retry` decorator only retries when the wrapped call *raises* (or, if explicitly configured, when `retry_if_result` matches) — decorating this function as-is with default `tenacity` retry-on-exception will **never trigger a retry on the exact 429 the research doc live-reproduced**, because no exception occurs.

The Rule as written ("wrapped in tenacity retry... before falling back to an empty result") is satisfiable by an implementer in a way that looks compliant but leaves the actual confirmed bug unfixed (e.g., adding `@retry` to the function without adding `resp.raise_for_status()` or a `retry_if_result(lambda r: r == [])` clause first). The Rule needs to explicitly require converting non-200/429 responses into a raised, retryable condition (or use `retry_if_result`) — otherwise it fails the checklist's "actually prevents its stated divergence" test.

### 4. [MEDIUM-HIGH] AD-4 binds `vision()` but its Rule only fixes `chat()`/`chat_json()` — and the un-fixed case already exists in the codebase

AD-4's binding list is `utils/azure_client.py (chat, chat_json, vision)`, but every sentence of the Rule talks only about `chat()`/`chat_json()` returning `Result[str, ErrorInfo]`. `vision()` is never mentioned again — not in the Rule, not in the Consistency Conventions' `Result`/`ErrorInfo` row, not in the Structural Seed.

This isn't a hypothetical gap: `vision()` has the identical sentinel-string bug today —

```python
except Exception as e:
    return f"[Vision unavailable: {e}]"
```

— and it is consumed exactly where the bug bites, in `pipeline/pdf_parser.py::_analyze_figures_with_vision`:

```python
desc = client.vision(...)
descriptions.append({"page": page_idx + 1, "description": desc})
```

A failed vision call silently becomes a fake-looking figure "description" appended to the paper's structured content, indistinguishable downstream from a real one — the same failure class AD-4 exists to eliminate, just on a different method. Binding `vision` in the header without a Rule that covers it means an implementer following the letter of AD-4 leaves this instance of the bug in place.

### 5. [MEDIUM] AD-6's Rule names one pooling call site; a second, structurally similar cross-paper OR-multiplication call site in the same file isn't mentioned

AD-6 prevents "risk ratios from different papers being multiplied together as if independently measured," and its Rule sends "cross-paper combination of odds/relative/hazard ratios" through `pipeline/pooling.py`. The Structural Seed only touches `simulation_engine.py`'s `combined_risk` (in `run_monte_carlo`).

But `run_bayesian_network` in the same file does its own independent sequential combination of odds ratios, potentially from different papers, via log-odds addition:

```python
for rp in risk_p[:6]:
    or_val = float(rp.get("value", 1.0)) * mod
    lo_inc = np.log(max(or_val, 0.01))
    combined_lo += lo_inc
```

This is the same class of problem AD-6 is meant to close (independently-estimated ORs from different papers combined as if compatible/independent) but via a different mechanism (sequential log-odds update instead of direct multiplication), and it isn't named in the Rule or the Structural Seed. Since AD-6's binding is phrased broadly ("`param_extractor.py` output consumed by `simulation_engine.py`") a strict reading covers it, but the concrete Rule text and Structural Seed — which is what an implementer will actually work from — only route `run_monte_carlo`'s path through pooling, leaving `run_bayesian_network`'s equivalent combination untouched. Worth an explicit line either binding it or explicitly deferring it with a reason (e.g., "different risk factors, not the same ratio pooled across studies, so out of scope").

### 6. [MEDIUM] Cache growth/retention for the new tables is a material operational gap the spine itself introduces, and it's not covered by the existing Deferred item

The checklist calls out the operational envelope specifically. The spine's only Deferred item on this axis is *"Concurrent/multi-user access to the SQLite cache — out of scope... single-user Streamlit session today."* That's a reasonable call, but it addresses **concurrency**, not **size**.

AD-2/AD-3 add three new tables (`wiki_pages`, `references`, `gap_validations`) that store full compiled JSON blobs keyed by content hash, with cache writes on every LLM/API-calling filter and no TTL, size cap, or pruning mechanism described anywhere in the Rule, Consistency Conventions, or Deferred. For a long-running local/Codespaces single-user session that's exactly the kind of app people leave running across many corpora over months, this is a real and foreseeable growth path (a local SQLite file with unbounded blob accumulation) that is a direct *consequence of this spine's own design*, not a pre-existing condition — so it isn't really deferrable as "unchanged by this spine" the way deployment/ops otherwise is. At minimum this needs one sentence acknowledging it's accepted (e.g., "no eviction; user can delete the DB file to reset; revisit if DB size becomes a practical problem") so it's a conscious decision rather than a silent gap.

### 7. [LOW] Stack table's `tenacity` version claim is asserted with a confidence marker but no traceable source

The Stack table states `tenacity | 9.1.4 (verified current on PyPI, requires Python >=3.10)`. Every other technology claim in the grounding research doc carries an inline citation (GitHub link, PyPI-adjacent source, etc.); the research doc's own `tenacity` mention cites only the general GitHub repo, with no version number at all. The spine introduces a specific patch version (9.1.4) and a Python floor (>=3.10) with a "verified current" assertion but no source for either number — making it unverifiable from the doc alone, per the checklist's instruction not to just trust the claim. This may well be accurate (tenacity has moved to 9.x, and this doc is dated 2026-07-31, so it's plausible), but as written it can't be checked against anything in the artifact chain and should either cite where it was verified or soften "verified current" to something that doesn't overclaim independent verification.

### 8. [LOW / note, not a defect] AD-2's binding list omission is benign but worth a one-line fix

AD-2 binds `wiki_compiler.compile_wiki_page`, `reference_extractor.enrich_reference`, `academic_search._assess_coverage` "(and any future filter that calls an LLM or external API per-item)." This catch-all phrase is doing real work already — e.g. `reference_extractor.py`'s eight `_ss_*`/`_crossref_*`/`_pubmed_*`/`_openalex_*` lookup functions are per-item external-API calls not literally named here (only `enrich_reference`, their caller, is named) but are the ones that actually need cache-aside treatment for the caching win to be real (caching only `enrich_reference`'s final composite result is fine and probably what's intended, but the wording is ambiguous about whether the *inner* lookups also need caching or just the outer wrapper). Recommend naming `enrich_reference` explicitly as "the single cache-checkpoint; its internal `_ss_*/_crossref_*/etc.` calls are not separately cached" to remove the ambiguity — not a blocking issue, just a clarity gap adjacent to finding #3/#5 above.

---

## Checklist-by-checklist summary

| Checklist item | Verdict |
|---|---|
| Fixes real divergence points, misses none | **Fails** — defect #4 (arXiv query) dropped entirely (Finding 1) |
| Every AD's Rule is enforceable and prevents its divergence | **Fails in part** — AD-5 (Finding 3) and AD-4 (Finding 4) have Rules narrower than their stated Prevents/Binds; AD-6 has an unaddressed sibling call site (Finding 5) |
| Nothing under Deferred lets units diverge at this altitude | **Mostly OK** — the three explicit Deferred items are reasonable calls; but cache retention isn't in Deferred at all when it should be (Finding 6) |
| Named tech is verified-current | **Mostly OK, one flag** — scipy/numpy claims are fine (existing pins); `tenacity` 9.1.4 claim is unsourced (Finding 7) |
| Ratifies rather than contradicts the brownfield codebase | **Fails** — AD-1's "already the case" claim is directly contradicted by three existing filter-to-filter imports (Finding 2) |
| No parent-spine inheritance section expected | **Correctly omitted** — standalone feature-altitude spine, no `binds` targets, this is fine |
| Every owned dimension decided/deferred/open, esp. operational envelope | **Thin** — the "Deployment & operations envelope" Deferred item covers infra/hosting but not the storage-growth concern this spine itself creates (Finding 6) |

## Overall

The spine's core technical judgment (cache-aside, DerSimonian-Laird pooling over naive multiplication, Result type at the LLM boundary, tenacity retry, confidence gating) is sound and well-matched to the research doc. The problems found are less about the *ideas* and more about **scope completeness and enforceability precision**: one confirmed defect quietly missing, one ratification claim that's checkably false against the current repo, and two Rules whose wording would pass a shallow read but not survive being carried out literally by whoever implements them. Recommend fixing Findings 1–3 before this spine moves out of draft; Findings 4–6 are worth a line each; 7–8 are polish.
