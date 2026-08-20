---
review-type: adversarial-incompatibility
target: ARCHITECTURE-SPINE.md (ResGap Pipeline Soundness & Caching Architecture)
date: 2026-07-31
reviewer-mandate: >
  Attack the spine as an adversary: construct two units one level down that each obey every AD
  to the letter yet still build incompatibly (clashing shared-data shapes, two owners of one
  entity, conflicting state-mutation paths). Every pair found is a hole to close with a new or
  tightened AD.
---

# Adversarial Incompatibility Review — ResGap Pipeline Soundness & Caching Architecture

## Verdict

**FAIL — not yet consistent enough to hand to two independent implementers.** The spine is
structurally sound at the paradigm level (pipes-and-filters, dependency direction) but four of
its six ADs contain under-specified shared-data shapes or scope gaps that let two rule-following
implementations diverge. Two of the findings (F2 and F6) are not mere ambiguity — they are
internal contradictions between the AD prose, the Consistency Conventions table, and the ERD, so
"obeying the letter" doesn't even resolve to a single reading. Six holes found, ranked by
severity.

---

## F1 (High) — `param_extractor.py` is a plausible LLM-calling filter that AD-2's bind list neither names nor covers via its "future filter" clause

**The two implementers:**
- **Dev A** reads AD-6's Prevents clause — "an LLM-invented number from vague language (e.g.
  'majority' → 60)... risk ratios from different papers" — and correctly infers that
  `param_extractor.py` calls the LLM once per paper/gap to extract parameters and assign
  `confidence`. Reasoning "this is exactly the per-item LLM-calling shape AD-2 exists to cover,"
  Dev A adds a fourth cache table (e.g. `param_extractions`) with a cache key improvised in the
  spirit of AD-3.
- **Dev B** reads AD-2's Binds line literally: `wiki_compiler.compile_wiki_page`,
  `reference_extractor.enrich_reference`, `academic_search._assess_coverage`, "**and any future
  filter** that calls an LLM or external API per-item." `param_extractor.py` already exists today
  — it is not a *future* filter — so the parenthetical doesn't reach it, and it isn't named
  explicitly. Dev B ships `param_extractor.py` with zero caching.

Both are defensible readings of the same text. The result: one build re-spends LLM tokens on
every re-run of `extract-params` (the exact waste AD-2 exists to prevent) while the other invents
an uncovered fourth cache-key scheme with no AD-3 entry to constrain its shape (own hash
algorithm, own separator, no `stage_logic_version` discipline) — two incompatible systems, both
spine-compliant.

**Close with:** Add `param_extractor.py`'s per-item LLM call to AD-2's Binds list explicitly (or
state explicitly that it is intentionally *out* of scope and why — e.g., "extraction happens once
per paper and is cheap enough to not need cache-aside"). Either way, AD-2's parenthetical should
read "any other existing or future filter" to close the tense loophole.

---

## F2 (High) — AD-3's rule text requires a domain hash in *every* cache key; the ERD explicitly omits it from `REFERENCES`

AD-3's Rule states: *"every cache key = hash(content) + hash(relevant domain_config) +
stage_logic_version"* — and AD-3's Binds line covers all three tables (`wiki_pages`,
`references`, `gap_validations`) uniformly. But the ERD schema block for `REFERENCES` lists only:

```
REFERENCES {
  string cache_key PK
  string doi_or_title_hash
  int stage_logic_version
  blob enriched_json
}
```

— no `domain_hash` field, unlike `WIKI_PAGES` and `GAP_VALIDATIONS`, which both carry one.

**The two implementers:**
- **Dev A** builds `reference_extractor.enrich_reference`'s cache key strictly from the ERD
  (source of truth for schema): `doi_or_title_hash:stage_logic_version`, no domain component.
- **Dev B** builds it strictly from the AD-3 prose rule (source of truth for behavior): `hash(content) + hash(relevant domain_config) + stage_logic_version`, i.e.
  `doi_or_title_hash:domain_hash:stage_logic_version`.

Both followed an authoritative part of the spine to the letter. The resulting cache tables have
different column counts and different key formats — an incompatible shared-data shape for the
same entity, and neither build is "wrong" per the text as written. This also leaves genuinely
unresolved whether reference enrichment prompts are domain-sensitive at all (if `enrich_reference`
injects domain-specific prompt text the way `compile_wiki_page` does, Dev A's build has the exact
stale-domain-serving bug AD-3 (a) was written to prevent).

**Close with:** Either (1) add `domain_hash` to the `REFERENCES` ERD entry and confirm
`enrich_reference` is domain-sensitive, or (2) explicitly narrow AD-3's rule to say the domain
component is omitted for `references` specifically because reference enrichment does not consume
`domain_config`. The spine must pick one and make the ERD and the prose agree.

---

## F3 (Medium-High) — Cache-write-after-`Failure` invariant doesn't pin where the try/except boundary sits relative to the write call

AD-4 says a `Failure` causes an immediate raise of `LLMCallError`; the Consistency Conventions
table separately states "cache writes happen only after a successful (non-`Failure`) result —
never cache a failure." These two rules are only consistent if the cache-write statement is
strictly downstream, in the same unguarded code path, of the `chat`/`chat_json` call — i.e., the
exception's propagation *is* the mechanism that skips the write. Nothing in AD-2 or AD-4 requires
that structure.

**The two implementers:**
- **Dev A** writes `compile_wiki_page` so the exception unwinds past the whole function body
  (caught only at the `app.py` orchestration level, which skips the paper entirely). No caching
  of a failure is possible — compliant.
- **Dev B**, following AD-4's own instruction that "pipeline stages continue to look like normal
  Python with try/except," puts a `try/except LLMCallError` *inside* `compile_wiki_page` itself,
  logs the error, and falls back to a degraded placeholder dict (e.g.
  `{"summary": "", "error": str(e)}`). Execution then falls through to the function's normal
  tail-end "write result to `wiki_pages` cache" line, because nothing in the function
  structurally distinguishes the happy-path tail from the error-handler's tail. Dev B's build now
  *does* cache a failure-derived value — silently violating "never cache a failure" while still
  satisfying AD-4's literal instruction to "raise ... rather than passing the error string
  further downstream" (the raise happened; it was just caught and locally recovered from).

Both are literal, defensible readings of "look like normal Python with try/except." The
cache-corruption outcome (a permanently-cached degraded wiki page for a paper that only failed
transiently) is exactly the kind of bug AD-2/AD-3 exist to prevent, yet neither AD forbids it.

**Close with:** Add an explicit sub-rule to AD-2 or AD-4: "if a filter catches `LLMCallError`
internally to degrade gracefully, the degraded/placeholder result must not reach the
cache-write call — either re-raise past it, or gate the write with an explicit success flag,
never a bare fall-through." State the invariant as a data-flow constraint, not just a
control-flow suggestion.

---

## F4 (Medium) — `hash(content)` and `hash(relevant domain_config)` pin neither algorithm nor serialization, risking both false cache hits and false cache misses

AD-3 never names a hash algorithm (MD5? SHA-1? SHA-256?) or a serialization procedure for
`domain_config` (a Python dict) before hashing. Two consequences, both real:

1. **False misses (efficiency bug, not correctness bug, but still spine-relevant since AD-2
   exists purely to stop wasted spend):** if `hash(relevant domain_config)` is computed as
   `hashlib.sha256(json.dumps(domain_config).encode())` without `sort_keys=True`, two logically
   identical domain configurations built via different code paths (different insertion order)
   hash differently, silently defeating the cache AD-2 mandates.
2. **Scope ambiguity in "relevant":** AD-3 says "hash(**relevant** domain_config)" — relevant
   to what, precisely? If one implementer hashes the whole `domain_config` dict and another
   hashes only the selected-domain name string, and the excluded fields (e.g. a prompt-template
   variant) actually do affect `compile_wiki_page`'s output, the second implementer reproduces
   the exact stale-domain-serving bug AD-3(a) exists to prevent — while technically having
   "hashed the relevant domain_config" by their own reading.

**Close with:** Pin the hash algorithm (e.g. "SHA-256, hex digest") and require
`json.dumps(obj, sort_keys=True)` (or equivalent canonical form) wherever a dict is hashed for a
cache key. Enumerate exactly which `domain_config` fields are "relevant" per stage (or state "the
entire `domain_config` dict, canonically serialized" as the default so there is no per-stage
judgment call).

---

## F5 (Medium) — AD-3's rule notation ("+") and the Consistency Conventions' pinned format (":") are not cross-referenced, and `chat_json`'s literal return type conflicts with its name

Two smaller but real gaps:

- **Cache key join character.** AD-3's Rule uses `+` ("hash(content) + hash(relevant
  domain_config) + stage_logic_version") which reads as generic composition/concatenation. The
  Consistency Conventions table separately pins `content_hash:domain_hash:stage_logic_version`
  (colon-joined). Nothing in AD-3 points to that table as the authoritative literal format, so an
  implementer working only from the Invariants section (reasonably treating it as the normative
  source, per the doc's own section title) could join fields with no separator, `_`, or any other
  character, since fixed-length hex digests make the ambiguity easy to miss until
  `stage_logic_version` grows past a single digit. **Close with:** restate the exact colon-joined
  literal format inside AD-3's own Rule text, not only in the cross-cutting table.

- **`chat_json`'s return type.** AD-4's Rule states flatly "`chat()`/`chat_json()` return
  `Result[str, ErrorInfo]`." A method named `chat_json` returning `Result[str, ...]` (a string,
  not a parsed object) is counter-intuitive; an implementer going by the name alone could
  reasonably type it as `Result[dict, ErrorInfo]` or `Result[Any, ErrorInfo]`, breaking every
  downstream caller that expects to run the existing 3-strategy JSON-fallback parser on a raw
  string (per the Consistency Conventions table, that fallback parsing is explicitly unchanged
  and expects string input). AD-4's Binds line also lists `vision()` but the Rule sentence never
  restates `vision()`'s return type, leaving it unclear whether vision calls follow the same
  `Result[str, ErrorInfo]` shape or something else (e.g., structured output). **Close with:**
  explicitly state `chat_json()` still returns `Success(value: str)` (the caller parses it), and
  add one sentence pinning `vision()`'s return type by name instead of relying on it being
  swept in by the Binds line.

---

## F6 (Low-Medium) — No AD extends cache-key discipline to any future non-LLM/API cache table (the simulation/pooling seam)

AD-2's scope is explicitly "any future filter that calls an LLM or external API per-item" —
`pipeline/pooling.py` and `simulation_engine.py`'s Monte Carlo sampling call neither, so today
they correctly fall outside AD-2/AD-3, and there is no simulation cache table in the ERD. That
part is internally consistent. The latent hole: nothing in the spine states that AD-3's key
composition and `stage_logic_version`-bump discipline is *the general pattern for any cache
table*, LLM/API-backed or not. If a future implementer adds memoization to expensive Monte Carlo
runs (a plausible, non-token-costing but still expensive operation) by analogy to the existing
three tables, there is no AD requiring them to version the cache key against pooling-logic
changes (e.g., switching the pooling estimator). A rule-following implementer could reasonably
conclude that because `simulation_engine.py`/`pooling.py` are not named in AD-2's Binds list,
*no* caching discipline — including version-bumping — applies to them at all, and cache stale
pooled results across a pooling-logic change indefinitely.

**Close with:** Add one sentence to AD-3 (or a new AD-7) generalizing: "Any cache table added to
`utils/database.py` in the future, regardless of whether it is LLM/API-backed, must follow this
cache-key composition and `stage_logic_version` discipline." This costs nothing today and closes
the seam before it's needed.

---

## Summary Table

| # | Severity | Incompatibility | Fix |
| --- | --- | --- | --- |
| F1 | High | `param_extractor.py`'s LLM call is un-owned by AD-2 (named nor "future") | Add to AD-2 Binds explicitly, or explicitly exclude with rationale |
| F2 | High | AD-3 prose requires domain_hash everywhere; ERD omits it from REFERENCES | Reconcile ERD and prose for `references` |
| F3 | Medium-High | Cache-write-after-Failure invariant isn't a data-flow rule, only a control-flow suggestion | Add explicit "degraded result must not reach cache-write" sub-rule |
| F4 | Medium | Hash algorithm + dict serialization for content/domain_config unpinned | Pin SHA-256 + canonical (sort_keys) serialization; enumerate "relevant" fields |
| F5 | Medium | Key-join notation ("+" vs ":") not cross-referenced; `chat_json` return type name/type mismatch | Restate literal key format in AD-3; pin `chat_json`/`vision` return types explicitly |
| F6 | Low-Medium | No AD generalizes cache-key/versioning discipline beyond the three named tables | Add a generalizing sentence or AD-7 |
