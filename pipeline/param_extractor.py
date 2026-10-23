"""
Stage 8: Quantitative Parameter Extractor — Enhanced
Fixes:
  - Linguistic-to-numeric conversion ("approximately one third" → 33.3%)
  - Cross-paper derived value computation
  - Richer sufficiency explanation (why score is low, what's missing)
  - Correct CSV generation
"""
import json
import re
import csv
import io
import logging
from utils.azure_client import unwrap, LLMCallError
from utils.cache_tag import model_tag
from utils.database import compute_cache_key, get_cached_parameters, save_cached_parameters
from pipeline.param_quality import annotate_parameters

logger = logging.getLogger(__name__)

# Bumped whenever PARAM_EXTRACTION_PROMPT changes, so old cached entries
# don't silently keep serving stale-logic results (AD-3).
# 2: the prompt now excludes laboratory protocol settings (a real run's parameters were mostly
# coating and staining concentrations, which no model can use).
PARAM_STAGE_VERSION = 4  # 3: parameters carry evidence_kind (measured/opinion) and sanity checks

PARAM_EXTRACTION_PROMPT = """You are a clinical biostatistician extracting quantitative parameters
from healthcare research paper summaries.

Extract the numerical values a quantitative model could use: prevalence, incidence, rates,
probabilities, effect sizes, risk or hazard ratios, treatment efficacy, survival, sensitivity,
specificity, costs, response rates, and MEASURED OUTCOMES with their values.

DO NOT extract laboratory protocol settings that describe how an experiment was set up rather than
what it found: reagent, coating, staining or cell-suspension concentrations, incubation times,
device or membrane dimensions, flow or pump settings used as setup, inoculum sizes, antibody
dilutions. Do not extract sample sizes, years, page or figure numbers.

Convert linguistic expressions to numbers:
  "approximately one third" → 33.3 (confidence: low)
  "nearly doubled" → use baseline × 2 (confidence: low)
  "significantly higher (p<0.05)" → flag as statistically significant, estimate if possible
  "majority of patients" → 60 (confidence: low, as conservative estimate)

Return ONLY a JSON array:
[
  {
    "name": "parameter_name_snake_case",
    "category": "prevalence|incidence|odds_ratio|relative_risk|hazard_ratio|transition_probability|efficacy|survival|sensitivity|specificity|mean|proportion|rate|other",
    "value": <float>,
    "ci_lower": <float or null>,
    "ci_upper": <float or null>,
    "unit": "percent|per_1000|per_year|absolute|ratio|dimensionless",
    "population": "who this applies to",
    "condition": "disease or clinical condition",
    "time_horizon": "5-year or annual or null",
    "source_paper": "paper title",
    "source_section": "Results|Table 2|Abstract|inferred",
    "confidence": "high|medium|low",
    "is_derived": false,
    "derivation_note": "null or how this was computed",
    "evidence_kind": "measured|opinion",
    "notes": "caveats"
  }
]
evidence_kind: "measured" for what a study FOUND about patients, biology or an intervention (a rate, an effect, an outcome value);
"opinion" for what respondents, experts or participants SAID they think, prefer, know or would do (e.g. "62% of respondents agree",
survey awareness, willingness, response rates). Opinions are kept but never used to simulate disease or survival."""

CROSS_PAPER_DERIVATION_PROMPT = """You are a biostatistician computing derived parameters
from values extracted across multiple research papers.

Given parameters already extracted from individual papers, compute NEW derived values
that combine information across papers:
  - Combined risk = baseline_prevalence × odds_ratio
  - Absolute risk reduction = control_rate - treatment_rate
  - Number needed to treat = 1 / absolute_risk_reduction
  - Population attributable fraction = (prevalence × (OR-1)) / (prevalence × (OR-1) + 1)
  - 10-year cumulative incidence from annual rate

Return ONLY a JSON array of NEW derived parameters (same format as input).
Set "is_derived": true and explain in "derivation_note" which source params were combined."""

SUFFICIENCY_CHECK_PROMPT = """You are assessing extracted parameters for computational modelling.

Return ONLY JSON:
{
  "sufficient": true or false,
  "minimum_viable_model": "description or null",
  "parameter_count": <int>,
  "coverage_score": <0-10>,
  "missing_critical": ["list of missing parameter types"],
  "recommendation": "proceed|warn_and_proceed|insufficient",
  "why_score_is_low": "specific explanation of what's missing and why it limits modelling",
  "what_would_improve_score": ["3-4 specific parameter types that would help most"]
}"""


def _is_confidently_empty(raw: str) -> bool:
    """True if raw, after stripping markdown fences, is a literal empty JSON
    array -- a genuine "no parameters found" response, not one where every
    parse strategy in _robust_parse failed and silently fell back to []."""
    if not raw:
        return False
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw).strip()
    try:
        return json.loads(cleaned) == []
    except Exception:
        return False


def _robust_parse(raw: str, expected: type = list):
    if not raw:
        return [] if expected == list else {}
    for strategy in [
        lambda s: s,
        lambda s: re.sub(r'^```(?:json)?\s*|\s*```$', '', s).strip(),
        lambda s: re.sub(r',\s*([}\]])', r'\1', s),
    ]:
        try:
            result = json.loads(strategy(raw))
            if isinstance(result, expected):
                return result
        except Exception:
            pass

    # Try to extract array or object
    for pattern, exp in [(r'\[.*\]', list), (r'\{.*\}', dict)]:
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
                if isinstance(result, expected):
                    return result
            except Exception:
                pass
    return [] if expected == list else {}


def extract_parameters(wiki: dict, papers: list, client, study_types: dict | None = None) -> list:
    """Extract all quantitative parameters including linguistic conversions. `study_types` maps a
    paper (filename or title) to its study type, so a survey paper's answers are tagged as opinions."""
    all_params = []
    study_types = dict(study_types or {})
    wiki_pages = list(wiki.get("pages", []))

    # B6 FIX: zip() silently truncates to the shorter list.
    # If wiki compilation failed for any paper, we'd silently lose those papers.
    # Pad wiki_pages with stub entries so every paper is always processed.
    if len(wiki_pages) < len(papers):
        start = len(wiki_pages)          # fixed before the loop: wiki_pages grows as stubs are appended
        for idx in range(start, len(papers)):
            wiki_pages.append({
                "title": papers[idx].get("filename", f"Paper {idx+1}"),
                "source_file": papers[idx].get("filename", ""),
                "key_findings": [], "limitations": [], "methods": [],
                "datasets": [], "contributions": [],
            })

    for i, (page, paper) in enumerate(zip(wiki_pages, papers)):
        title = page.get("title", page.get("source_file", f"Paper {i+1}"))

        context_parts = [f"Paper: {title}"]

        for field in ["key_findings", "limitations", "methods", "datasets", "contributions"]:
            items = page.get(field, [])
            if items:
                context_parts.append(field.upper() + ":\n" + "\n".join(f"- {x}" for x in items))

        sections = paper.get("sections", {})
        matched_chars = 0
        matched_names = set()
        for sec_name, sec_text in sections.items():
            if any(k in sec_name.lower() for k in [
                "result", "statistic", "table", "finding",
                "outcome", "survival", "efficacy", "method", "discussion"
            ]) and str(sec_text).strip():
                chunk = str(sec_text)[:3000]
                context_parts.append(f"[{sec_name}]\n{chunk}")
                matched_chars += len(chunk)
                matched_names.add(sec_name)
        if matched_chars < 4000:
            # Papers headed by topic ("3.1 The human CF airway chip") keep their
            # numbers under headings with no keyword, and a bare "Results"
            # heading can be empty. Top up from the other sections' openings.
            budget = 12000 - matched_chars
            for sec_name, sec_text in sections.items():
                if budget <= 0:
                    break
                if sec_name in matched_names or sec_name == "References" or not str(sec_text).strip():
                    continue
                chunk = str(sec_text)[:min(1500, budget)]
                context_parts.append(f"[{sec_name}]\n{chunk}")
                budget -= len(chunk)

        for tbl in paper.get("tables", [])[:6]:
            context_parts.append(f"[Table p.{tbl.get('page')}]\n{tbl['content'][:1200]}")

        context = "\n\n".join(context_parts)

        # B16 fix: check the cache before calling the LLM (Story 2.2 / AD-2 /
        # AD-3). Keyed on `context` (the wiki-derived LLM input), NOT
        # paper["full_text"] — this stage's actual input changes whenever the
        # wiki page changes, even if the raw paper text doesn't.
        cache_key, content_hash, _ = compute_cache_key(context, None, [], PARAM_STAGE_VERSION, model_tag=model_tag(client))
        cached = get_cached_parameters(cache_key)
        if cached is not None:
            params = cached
        else:
            user_prompt = (
                f"Extract ALL quantitative parameters from this paper, including linguistic estimates.\n"
                f"Source paper: \"{title}\"\n\n{context}"
            )
            try:
                raw = unwrap(client.chat_json(PARAM_EXTRACTION_PROMPT, user_prompt, max_tokens=6000))
                params = _robust_parse(raw, list)
                # B16 fix: cache the raw, pre-augmentation params — paper_index
                # below is only valid for THIS call, never cache it.
                # Review fix: only cache when params is non-empty (a genuine
                # extraction) or the LLM's raw response was confidently an
                # empty array -- never cache a [] that _robust_parse produced
                # because every parse strategy failed on a garbled/truncated
                # response, which would freeze a transient failure forever.
                if params or _is_confidently_empty(raw):
                    save_cached_parameters(cache_key, content_hash, PARAM_STAGE_VERSION, params)
            except LLMCallError as e:
                logger.warning("Parameter extraction failed for %r (%s); skipping this paper",
                               title, getattr(getattr(e, "error", None), "kind", "unknown"))
                # B12 fix: don't abort extraction for every remaining paper just
                # because one paper's LLM call failed — skip this paper's params
                # (consistent with the B6 FIX philosophy above: never silently
                # lose a paper from processing, but here there's nothing to keep).
                # B16 fix: never cache this path.
                params = []

        stype = study_types.get(paper.get("filename")) or study_types.get(title)
        for p in params:
            if not isinstance(p, dict):
                continue
            p["paper_index"]  = i
            p["source_paper"] = p.get("source_paper") or title
            p["source_file"]  = paper.get("filename", "")
            p.setdefault("is_derived", False)
            p.setdefault("derivation_note", None)
            if stype:
                study_types.setdefault(p["source_paper"], stype)

        all_params.extend(params)

    annotate_parameters(all_params, study_types)
    return all_params


def derive_cross_paper_parameters(params: list, client) -> list:
    """
    Compute new parameters by combining values across papers.
    Returns only the NEW derived params (not the originals).
    """
    if len(params) < 2:
        return []

    sample = params[:20]
    user_prompt = (
        f"Given these {len(params)} extracted parameters (sample shown):\n"
        f"{json.dumps(sample, indent=2)}\n\n"
        "Compute NEW cross-paper derived values. Only return derivable ones."
    )

    raw = unwrap(client.chat_json(CROSS_PAPER_DERIVATION_PROMPT, user_prompt, max_tokens=3000))
    derived = _robust_parse(raw, list)

    result = []
    for p in derived:
        if isinstance(p, dict):
            p["is_derived"] = True
            # Review fix (Story 3.1): CROSS_PAPER_DERIVATION_PROMPT doesn't
            # explicitly request a confidence field, and simulation_engine's
            # new confidence gate (AD-6) treats a missing field as excluded.
            # A derived value is a computed combination of already-extracted
            # source values, not an invented guess from vague language --
            # default it to "medium" rather than letting an unrelated
            # prompt-schema gap silently starve the simulation of legitimate
            # cross-paper-derived data.
            p.setdefault("confidence", "medium")
            result.append(p)
    return result


def check_sufficiency(params: list, client) -> dict:
    if not params:
        return {
            "sufficient": False,
            "recommendation": "insufficient",
            "parameter_count": 0,
            "coverage_score": 0,
            "missing_critical": ["No parameters extracted"],
            "minimum_viable_model": None,
            "why_score_is_low": "No numerical data could be extracted from the papers.",
            "what_would_improve_score": [
                "Papers with explicit numerical results tables",
                "Prevalence or incidence rates",
                "Odds ratios or relative risks",
                "Transition probabilities or survival rates",
            ],
        }

    summary = {
        "total_params":    len(params),
        "categories":      list(set(p.get("category", "") for p in params)),
        "conditions":      list(set(p.get("condition", "") for p in params))[:10],
        "params_with_ci":  sum(1 for p in params if p.get("ci_lower") is not None),
        "derived_params":  sum(1 for p in params if p.get("is_derived")),
        "high_confidence": sum(1 for p in params if p.get("confidence") == "high"),
        "sample":          params[:6],
    }

    raw = unwrap(client.chat_json(
        SUFFICIENCY_CHECK_PROMPT,
        f"Parameters summary:\n{json.dumps(summary, indent=2)}",
        max_tokens=1000,
    ))

    result = _robust_parse(raw, dict)
    if not isinstance(result, dict):
        result = {}

    result["parameter_count"] = len(params)
    result.setdefault("coverage_score", min(10, len(params)))
    result.setdefault("sufficient", len(params) >= 3)
    result.setdefault("recommendation", "warn_and_proceed")
    result.setdefault("why_score_is_low", "Assessment pending.")
    result.setdefault("what_would_improve_score", [])
    return result


def params_to_csv(params: list) -> str:
    fieldnames = [
        "name", "category", "value", "ci_lower", "ci_upper",
        "unit", "population", "condition", "time_horizon",
        "source_paper", "source_section", "confidence",
        "is_derived", "derivation_note", "notes",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    if not params:
        writer.writerow({"name": "No parameters extracted"})
    else:
        for p in params:
            writer.writerow({k: p.get(k, "") for k in fieldnames})
    return output.getvalue()


def group_params_by_category(params: list) -> dict:
    groups = {}
    for p in params:
        cat = p.get("category", "other")
        groups.setdefault(cat, []).append(p)
    return groups
