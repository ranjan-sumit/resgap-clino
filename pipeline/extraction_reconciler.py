"""
Stage 1 reconciliation (Clinova Phase 1, Epic 1.1, Stories 1.1.3-1.1.4):
combines independent PyMuPDF (pipeline/pdf_parser.py) and Docling
(pipeline/docling_parser.py) extractions for one paper into a canonical
representation, per 05-data-architecture.md §3's ExtractedField schema --
applied here to the subset of fields both parsers can produce
deterministically today (full_text, doi, tables). Title/authors/abstract/
methodology/etc. remain LLM-derived via pipeline/wiki_compiler.py for now,
unchanged -- full semantic-field reconciliation is later Phase 1 iteration
scope, not claimed by this module.

When parsers disagree, every candidate value is retained (never silently
discarded) -- this is the direct implementation of Problem A's "detect,
measure, and prevent silent information loss" requirement.
"""
import re

RECONCILIATION_STAGE_VERSION = 1

# Deterministic DOI pattern -- same shape used across CrossRef/Semantic
# Scholar/OpenAlex metadata (10.NNNN/suffix).
_DOI_PATTERN = re.compile(r'\b10\.\d{4,9}/[^\s"<>]+\b')


def _clean_doi(raw: str) -> str:
    return raw.rstrip('.,;)]}>"\'')


def _extract_doi_candidate(text: str) -> tuple[str | None, float | None]:
    """Returns (doi_value, position_fraction) -- position_fraction is the
    match's start offset as a fraction of total text length (0.0 = very
    start, 1.0 = very end), used to disambiguate a paper's own DOI (front
    matter, low fraction) from an unrelated DOI mentioned later in the text
    (e.g. a data/code-availability statement -- live-validated on real data,
    see evals/benchmarks/baseline/doi-disambiguation-note.md)."""
    if not text:
        return None, None
    match = _DOI_PATTERN.search(text)
    if not match:
        return None, None
    return _clean_doi(match.group()), match.start() / len(text)


def reconcile_paper(pymupdf_result: dict, docling_result: dict, filename: str) -> dict:
    """Reconcile two independent parser extractions of the same paper.
    Never discards a disagreeing candidate -- all candidate values are
    retained under `fields.<name>.candidates`."""
    pymupdf_text = pymupdf_result.get("full_text", "") or ""
    docling_text = docling_result.get("full_text", "") or ""

    fields = {}

    # -- full_text: prefer the longer extraction as canonical (more content
    # captured), retain both. A large length disagreement is itself a
    # data-loss signal worth surfacing, not silently resolved away.
    pymupdf_chars = len(pymupdf_text)
    docling_chars = len(docling_text)
    if pymupdf_chars == 0 and docling_chars == 0:
        text_confidence, canonical_source, canonical_text = "low", "none", ""
    else:
        canonical_source = "docling" if docling_chars >= pymupdf_chars else "pymupdf"
        canonical_text = docling_text if canonical_source == "docling" else pymupdf_text
        longer, shorter = max(pymupdf_chars, docling_chars), min(pymupdf_chars, docling_chars)
        text_confidence = "high" if longer == 0 or shorter / longer >= 0.7 else "medium"

    fields["full_text"] = {
        "value": canonical_text,
        "source": canonical_source,
        "confidence": text_confidence,
        "candidates": [
            {"source": "pymupdf", "char_count": pymupdf_chars},
            {"source": "docling", "char_count": docling_chars},
        ],
    }

    # -- doi: cross-check both parsers' independently-extracted text for a
    # DOI pattern. Direct mitigation for the truncated-DOI finding from
    # Phase 0 (evals/benchmarks/baseline/phase0-findings.md,
    # case-truncated-doi.json) -- a DOI truncated by one extraction path
    # can still be recovered intact from the other.
    doi_pymupdf, pos_pymupdf = _extract_doi_candidate(pymupdf_text)
    doi_docling, pos_docling = _extract_doi_candidate(docling_text)

    if doi_pymupdf and doi_docling and doi_pymupdf == doi_docling:
        doi_value, doi_confidence, doi_source = doi_pymupdf, "high", "both"
    elif doi_pymupdf and doi_docling and (
        doi_docling.startswith(doi_pymupdf) or doi_pymupdf.startswith(doi_docling)
    ):
        # One candidate is a truncated prefix of the other -- a `\b`
        # word-boundary match stopping at a hyphen with nothing after it is
        # a common real cause (test_truncated_doi_in_one_source_recovered_
        # from_the_other). Prefer the longer, fuller candidate.
        if len(doi_docling) >= len(doi_pymupdf):
            doi_value, doi_source = doi_docling, "docling"
        else:
            doi_value, doi_source = doi_pymupdf, "pymupdf"
        doi_confidence = "medium"
    elif doi_pymupdf and doi_docling:
        # Two genuinely DIFFERENT DOIs, not a truncation of one another --
        # live-validated on real data (evals/benchmarks/baseline/
        # doi-disambiguation-note.md): a paper's own DOI reliably appears
        # very early in the text (front matter/header), while an unrelated
        # DOI (e.g. a linked OSF/dataset repository, mentioned in a Data
        # Availability statement) appears much later. An earlier version of
        # this function used "prefer the longer string" here, which is not
        # a principled signal for this case -- it happened to pick the
        # right answer on that first real paper by coincidence, not because
        # length actually indicates which DOI belongs to the paper itself.
        # Position fractions are only trustworthy when the two texts are
        # comparable in length (the same 0.7 ratio the full_text confidence
        # uses): a heavily truncated extraction's positions are stretched
        # toward 1.0, so its fraction ranking is meaningless. When they are
        # not comparable, fall back to absolute offsets.
        longer = max(pymupdf_chars, docling_chars)
        shorter = min(pymupdf_chars, docling_chars)
        texts_comparable = longer == 0 or shorter / longer >= 0.7
        if texts_comparable:
            pos_pymupdf_cmp, pos_docling_cmp = pos_pymupdf, pos_docling
        else:
            pos_pymupdf_cmp = pos_pymupdf * pymupdf_chars
            pos_docling_cmp = pos_docling * docling_chars
        if pos_pymupdf_cmp <= pos_docling_cmp:
            doi_value, doi_source = doi_pymupdf, "pymupdf"
        else:
            doi_value, doi_source = doi_docling, "docling"
        doi_confidence = "medium"
    elif doi_pymupdf or doi_docling:
        doi_value = doi_pymupdf or doi_docling
        doi_confidence, doi_source = "medium", ("pymupdf" if doi_pymupdf else "docling")
    else:
        doi_value, doi_confidence, doi_source = None, "low", "none"

    fields["doi"] = {
        "value": doi_value,
        "source": doi_source,
        "confidence": doi_confidence,
        "candidates": [
            {"source": "pymupdf", "value": doi_pymupdf},
            {"source": "docling", "value": doi_docling},
        ],
        "needs_llm_recovery": doi_value is None,
    }

    # -- tables: Docling is the stronger table extractor
    # (05-data-architecture.md §2) -- prefer it as canonical when it found
    # any, but retain PyMuPDF's candidates too.
    pymupdf_tables = pymupdf_result.get("tables", []) or []
    docling_tables = docling_result.get("tables", []) or []
    if docling_tables:
        tables_value, tables_source, tables_confidence = docling_tables, "docling", "high"
    elif pymupdf_tables:
        tables_value, tables_source, tables_confidence = pymupdf_tables, "pymupdf", "medium"
    else:
        tables_value, tables_source, tables_confidence = [], "none", "low"

    fields["tables"] = {
        "value": tables_value,
        "source": tables_source,
        "confidence": tables_confidence,
        "candidates": [
            {"source": "pymupdf", "count": len(pymupdf_tables)},
            {"source": "docling", "count": len(docling_tables)},
        ],
    }

    return {
        "filename": filename,
        "reconciliation_stage_version": RECONCILIATION_STAGE_VERSION,
        "fields": fields,
    }


def recover_doi_via_llm(reconciled: dict, client) -> dict:
    """Story 1.1.4: LLM recovery only for genuinely unresolved fields.
    Called only when both deterministic parsers failed to find a DOI
    (needs_llm_recovery=True) -- never for a field the parsers already
    resolved, agreeing or not (04-ai-research-architecture.md §2's LLM-use
    discipline: reserve LLM calls for what deterministic code can't do)."""
    doi_field = reconciled["fields"]["doi"]
    if not doi_field.get("needs_llm_recovery"):
        return reconciled

    from utils.azure_client import unwrap

    excerpt = (reconciled["fields"]["full_text"].get("value") or "")[:3000]
    if not excerpt.strip():
        return reconciled  # nothing to recover from

    system = (
        "You extract a single bibliographic field from research paper text. "
        "Return ONLY the DOI (format 10.NNNN/suffix) if one appears in the "
        "text, or the exact string NONE if no DOI is present. No other output, "
        "no explanation, no markdown."
    )
    raw = unwrap(client.chat(system, excerpt, temperature=0.0, max_tokens=50))
    candidate = (raw or "").strip().strip('"').strip("`")

    if candidate and candidate.upper() != "NONE" and re.match(r'^10\.\d{4,9}/', candidate):
        doi_field["value"] = _clean_doi(candidate)
        doi_field["source"] = "llm_recovery"
        doi_field["confidence"] = "medium"
        doi_field["needs_llm_recovery"] = False

    return reconciled
