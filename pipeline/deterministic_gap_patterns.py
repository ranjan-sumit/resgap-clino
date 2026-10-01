"""
Deterministic Gap Pattern Library (Clinova Phase 3, Epic 3.2 — Hybrid Gap
Engine, signal source 1 of 3, per 04-ai-research-architecture.md §4).

Evaluates a versioned, code-defined rule set directly against a corpus's
Evidence Objects (Phase 2) -- no LLM call for the trigger check itself,
per §2's LLM-use discipline ("use LLM only for difficult scientific
extraction, not for re-deriving what's already been extracted"). Patterns
are drawn from `_bmad-output/clinova/domain-patterns-healthcare-ai.md`,
itself grounded in TRIPOD+AI/PROBAST/CONSORT-AI -- that document is
`status: draft-needs-expert-review`, and this implementation inherits the
same caveat: the KEYWORD LISTS are a best-effort heuristic (substring
matching on Evidence Object text), not validated clinical NLP. False
negatives (a pattern that should fire but doesn't, because the paper used
different wording) are the expected failure mode of a keyword heuristic --
consistent with this project's False-Novelty-Rate-first philosophy
(missing a real gap is preferred over inventing a false one).

A pattern fires at the CORPUS level, not per-paper: "no paper in this
corpus reports X" is the actual gap-in-the-field claim a research-gap
analysis makes (a paper the corpus DOES cover for X is not a gap just
because a different paper in the same corpus omits it). The one exception
is NAMED_LIMITATION, which is inherently per-paper (a paper's own
self-reported limitation is not something another paper could "cover").
"""
import re

from packages.research_schemas.gap_identity import attach_gap_identity

# Bumped whenever PATTERNS' trigger logic or keyword lists change, so a gap
# produced under an old pattern version can be distinguished if this output
# is ever cached (mirrors this codebase's stage_logic_version convention,
# AD-3) -- not currently cached (cheap enough to recompute every run), but
# versioned defensively in case a future caller adds caching.
GAP_PATTERN_LIBRARY_VERSION = 1

# Domains this library applies to. Extending to other domains means writing
# domain-appropriate patterns, not reusing healthcare keywords -- deferred
# until a domain expert (or explicit user request, per this library's own
# origin) asks for it.
_APPLICABLE_DOMAINS = ("Healthcare AI",)


def _norm(text: str) -> str:
    return (text or "").lower()


# Real-data finding (2026-08-21, validated against the AuDHD_1/AuDHD_2
# corpus): a paper's own FutureWork evidence describes what the AUTHORS
# RECOMMEND doing next ("perform prospective longitudinal studies..."), not
# what already happened -- treating it as a positive keyword match for a
# "no_keyword" pattern like no_prospective_deployment_evidence silently
# suppressed a gap that should have fired (the recommendation is itself
# confirmation the gap is real, not evidence against it). Excluded from the
# "search all evidence types" default for every no_keyword pattern that
# doesn't explicitly opt in via `search_types`.
_FUTURE_INTENT_TYPE = "FutureWork"


def _any_keyword(text_lower: str, keywords: tuple) -> bool:
    return any(kw in text_lower for kw in keywords)


def _negation_guarded_text(text_lower: str, negation_phrases: tuple) -> str:
    """Blank out negated occurrences of an availability-style keyword so a
    statement like "data not publicly available" can't suppress the
    no_data_code_availability gap it actually affirms. See that pattern's
    `negation_phrases` entry."""
    for phrase in negation_phrases:
        text_lower = text_lower.replace(phrase, " ")
    return text_lower


# Each pattern: id, name, gap_type (matches the existing lowercase UI enum
# used by pipeline/gap_detector.py's LLM prompt: methodology|application|
# dataset|evaluation|theory|benchmark), why, and a trigger spec.
#
# mode="absence": fires if NO evidence object of `evidence_types` exists
#   anywhere in the corpus.
# mode="no_keyword": fires if evidence objects of `requires_types` exist
#   somewhere in the corpus (guards against firing on a plain extraction
#   gap rather than a real reported-vs-not gap) AND none of the corpus's
#   evidence text (searched across `search_types`, or all types if empty)
#   contains any of `keywords`.
# mode="keyword_present": fires if ANY evidence object of `search_types`
#   contains one of `keywords` (a directly-stated negative signal, e.g.
#   the paper says "single-center" outright) AND (if `exclude_keywords`
#   given) none of that same evidence also contains a counter-keyword.
PATTERNS = [
    {
        "id": "missing_external_validation", "gap_type": "evaluation",
        "name": "Missing external validation",
        "why": "Internal-only validation is the single most common reason a published medical-AI result fails to replicate (TRIPOD+AI item 13).",
        "mode": "no_keyword",
        "requires_types": ("DatasetPopulation",),
        "search_types": ("DatasetPopulation", "Method", "StudyDesign"),
        "keywords": ("external validation", "held-out", "held out", "independent cohort",
                     "external cohort", "external dataset", "different institution",
                     "different site", "different center", "multi-site", "multi-institutional",
                     "external test set", "multicenter", "multi-centre"),
    },
    {
        "id": "single_center_study", "gap_type": "dataset",
        "name": "Single-center study",
        "why": "Site-specific artifacts (scanner type, local population, clinical workflow) routinely inflate apparent performance.",
        "mode": "keyword_present",
        "search_types": ("DatasetPopulation", "StudyDesign"),
        "keywords": ("single-center", "single center", "single-centre", "single centre",
                     "single institution", "one hospital", "one institution", "one site"),
    },
    {
        "id": "retrospective_only_design", "gap_type": "methodology",
        "name": "Retrospective-only design",
        "why": "Retrospective data has known biases (selection, label leakage from post-hoc chart review) that prospective studies avoid.",
        "mode": "keyword_present",
        "search_types": ("StudyDesign",),
        "keywords": ("retrospective",),
        "exclude_keywords": ("prospective",),
    },
    {
        "id": "no_temporal_shift_validation", "gap_type": "evaluation",
        "name": "No temporal/dataset-shift validation",
        "why": "Medical practice and patient populations drift; a model validated once may already be stale.",
        "mode": "no_keyword",
        "requires_types": ("DatasetPopulation",),
        "search_types": (),
        "keywords": ("temporal validation", "dataset shift", "distribution shift",
                     "different time period", "later cohort", "subsequent cohort",
                     "prospective follow-up", "time-based split"),
    },
    {
        "id": "missing_calibration_assessment", "gap_type": "evaluation",
        "name": "Missing calibration assessment",
        "why": "A well-discriminating model can still be badly miscalibrated, which matters directly for clinical decision thresholds (PROBAST domain 4).",
        "mode": "no_keyword",
        "requires_types": ("Metric",),
        "search_types": ("Metric",),
        "keywords": ("calibration", "brier score", "brier", "hosmer-lemeshow", "hosmer lemeshow"),
    },
    {
        "id": "limited_nondiverse_population", "gap_type": "dataset",
        "name": "Limited/non-diverse population",
        "why": "A population skewed toward one ancestry/ethnicity/geography with no stated diversity limits generalizability.",
        "mode": "keyword_present",
        "search_types": ("DatasetPopulation",),
        "keywords": ("european ancestry", "predominantly white", "primarily caucasian",
                     "single ethnicity", "homogeneous population", "lack of diversity",
                     "limited diversity", "underrepresented"),
    },
    {
        "id": "missing_demographic_subgroup_analysis", "gap_type": "evaluation",
        "name": "Missing demographic subgroup analysis",
        "why": "Aggregate performance can hide a model that fails badly for an underrepresented subgroup.",
        "mode": "no_keyword",
        "requires_types": ("Metric",),
        "search_types": ("Metric", "Result"),
        "keywords": ("subgroup", "stratified by", "by sex", "by age", "by ethnicity",
                     "by race", "by gender", "demographic breakdown", "stratified analysis"),
    },
    {
        "id": "no_fairness_bias_testing", "gap_type": "evaluation",
        "name": "No fairness/bias testing",
        "why": "Absence of any fairness framing at all is a stronger signal than a subgroup analysis that merely under-covers some groups.",
        "mode": "no_keyword",
        "requires_types": ("DatasetPopulation", "Metric"),
        "search_types": (),
        "keywords": ("fairness", "demographic parity", "equalized odds", "bias audit",
                     "algorithmic bias", "disparate impact", "subgroup calibration",
                     "equity analysis"),
    },
    {
        "id": "small_sample_no_power_justification", "gap_type": "methodology",
        "name": "No sample-size/power justification",
        "why": "Under-powered studies produce unstable estimates and overfit-prone models.",
        "mode": "no_keyword",
        "requires_types": ("DatasetPopulation",),
        "search_types": ("DatasetPopulation", "Method"),
        "keywords": ("power analysis", "power calculation", "sample size justification",
                     "a priori power", "sample size calculation"),
    },
    {
        "id": "no_missing_data_handling", "gap_type": "methodology",
        "name": "No missing-data handling described",
        "why": "Silent imputation or listwise deletion can introduce bias undetectable from the reported results alone.",
        "mode": "no_keyword",
        "requires_types": ("DatasetPopulation",),
        "search_types": ("Method",),
        "keywords": ("missing data", "imputation", "imputed", "listwise deletion",
                     "multiple imputation", "missingness"),
    },
    {
        "id": "missing_benchmark_comparison", "gap_type": "benchmark",
        "name": "Missing benchmark/baseline comparison",
        "why": "A model's real value is only visible relative to the current standard of care or a strong existing method, not a strawman.",
        "mode": "absence",
        "evidence_types": ("ComparatorBaseline",),
    },
    {
        "id": "no_clinical_standard_of_care_comparison", "gap_type": "application",
        "name": "No comparison to clinical standard of care",
        "why": "The clinically relevant question is \"better than current practice,\" not \"better than a different algorithm.\"",
        "mode": "no_keyword",
        "requires_types": ("ComparatorBaseline",),
        "search_types": ("ComparatorBaseline",),
        "keywords": ("clinician", "radiologist", "physician", "standard of care",
                     "clinical expert", "current practice", "usual care", "treating physician"),
    },
    {
        "id": "no_explainability_analysis", "gap_type": "methodology",
        "name": "No explainability/interpretability analysis",
        "why": "Regulatory and clinical-adoption pathways for opaque models increasingly require some interpretability account.",
        "mode": "no_keyword",
        "requires_types": ("Method", "InterventionModel"),
        "search_types": (),
        "keywords": ("explainab", "interpretab", "shap", "lime", "attention visualization",
                     "feature importance", "grad-cam", "saliency"),
    },
    {
        "id": "no_prospective_deployment_evidence", "gap_type": "application",
        "name": "No prospective/real-world deployment evidence",
        "why": "The gap between offline validation and real clinical workflow integration is a widely-documented failure point for medical AI.",
        "mode": "no_keyword",
        "requires_types": ("StudyDesign",),
        "search_types": (),
        "keywords": ("prospective", "clinical pilot", "real-world deployment",
                     "field study", "live deployment", "clinical trial",
                     "prospective validation", "deployed in clinic"),
    },
    {
        "id": "no_cost_effectiveness_analysis", "gap_type": "application",
        "name": "No cost-effectiveness or workflow-impact analysis",
        "why": "Even an accurate model can fail adoption if it doesn't fit clinical workflow or isn't cost-justified.",
        "mode": "no_keyword",
        "requires_types": ("ComparatorBaseline", "InterventionModel"),
        "search_types": (),
        "keywords": ("cost-effectiveness", "cost effectiveness", "workflow impact",
                     "clinician time", "health-economic", "health economic",
                     "time savings", "cost analysis", "economic evaluation"),
    },
    {
        "id": "no_regulatory_safety_framing", "gap_type": "application",
        "name": "No regulatory/safety framing",
        "why": "For anything positioned toward clinical use, absence of this framing is itself a real, reportable gap.",
        "mode": "no_keyword",
        "requires_types": ("InterventionModel",),
        "search_types": (),
        "keywords": ("fda", "ce mark", "regulatory", "clearance", "approval pathway",
                     "safety monitoring", "post-market surveillance", "risk management"),
    },
    {
        "id": "no_data_code_availability", "gap_type": "methodology",
        "name": "No data/code availability statement",
        "why": "Directly blocks external validation by anyone else -- compounds the missing-external-validation pattern above.",
        "mode": "no_keyword",
        "requires_types": ("Method",),
        "search_types": (),
        "keywords": ("code available", "data available", "github.com", "open-source",
                     "open source", "data access", "upon reasonable request",
                     "publicly available", "repository"),
        # Negation guard: "data not publicly available" / "no repository"
        # AFFIRMS this gap, but it still contains the positive keyword --
        # negated occurrences are blanked before the keyword check so they
        # can't suppress the gap.
        "negation_phrases": ("not publicly available", "not made publicly available",
                             "not available", "no repository", "not released",
                             "not open-source", "not open source",
                             "code not available", "data not available"),
    },
    {
        "id": "unreported_class_imbalance_handling", "gap_type": "evaluation",
        "name": "Ambiguous/unreported class imbalance handling",
        "why": "A model can score well on ROC-AUC on an imbalanced task while being clinically useless.",
        "mode": "no_keyword",
        "requires_types": ("Metric", "DatasetPopulation"),
        "search_types": ("Metric", "Method"),
        "keywords": ("class imbalance", "class weighting", "pr-auc", "precision-recall auc",
                     "oversampl", "undersampl", "smote", "imbalanced"),
    },
]

_GAP_TYPE_KEYWORDS = (
    ("dataset", ("dataset", "population", "cohort", "sample")),
    ("evaluation", ("evaluat", "metric", "validat", "test set")),
    ("application", ("deploy", "clinical practice", "workflow", "regulatory")),
    ("benchmark", ("baseline", "benchmark", "compar")),
)


def _guess_gap_type(limitation_text: str) -> str:
    low = _norm(limitation_text)
    for gap_type, keywords in _GAP_TYPE_KEYWORDS:
        if _any_keyword(low, keywords):
            return gap_type
    return "methodology"


def _corpus_text(evidence_objects_by_paper: dict, types: tuple) -> str:
    parts = []
    for objs in evidence_objects_by_paper.values():
        for o in objs:
            etype = o.get("evidence_type")
            if types:
                if etype in types:
                    parts.append(o.get("text", ""))
            elif etype != _FUTURE_INTENT_TYPE:
                parts.append(o.get("text", ""))
    return _norm(" \n ".join(parts))


def _corpus_has_type(evidence_objects_by_paper: dict, types: tuple) -> bool:
    for objs in evidence_objects_by_paper.values():
        for o in objs:
            if o.get("evidence_type") in types:
                return True
    return False


def _matching_evidence(evidence_objects_by_paper: dict, types: tuple, keywords: tuple) -> list[dict]:
    """Evidence items (across the corpus) that DID contain one of `keywords`
    -- used to build a `not_present` gap's negative-evidence trail (which
    items were checked and found silent, not which item proves the gap)."""
    hits = []
    for paper_id, objs in evidence_objects_by_paper.items():
        for o in objs:
            etype = o.get("evidence_type")
            if types:
                if etype not in types:
                    continue
            elif etype == _FUTURE_INTENT_TYPE:
                continue
            if _any_keyword(_norm(o.get("text", "")), keywords):
                hits.append({**o, "paper_id": o.get("paper_id") or paper_id})
    return hits


def _make_gap(pattern: dict, all_paper_ids: list, evidence_refs: list[dict] = None) -> dict:
    evidence_lines = [f"Pattern check: {pattern['why']}"]
    for ref in (evidence_refs or [])[:5]:
        evidence_lines.append(f"{ref.get('paper_id', '?')} ({ref.get('evidence_type', '?')}): {ref.get('text', '')[:200]}")
    gap = {
        "title": pattern["name"],
        "description": pattern["why"],
        "gap_type": pattern["gap_type"],
        "confidence": "medium",
        "evidence": evidence_lines,
        "supporting_papers": list(all_paper_ids),
        "missing_connection": pattern["name"],
        "why_important": pattern["why"],
        "validation_status": "pending",
        "existing_papers": [],
        "source": "deterministic",
        "pattern_id": pattern["id"],
    }
    # Clinova Phase 4, Epic 4.4 (Scientific Lineage): evidence_refs already
    # carries real evidence_id values (spread from real Evidence Objects in
    # _matching_evidence()) -- wire them in rather than discarding them
    # into the free-text evidence_lines above only. "absence"/"no_keyword"
    # patterns pass no evidence_refs (the gap IS the absence of a match),
    # so those honestly get evidence_basis="absence_of_evidence" and an
    # empty motivating_evidence_ids -- never fabricated.
    motivating_evidence_ids = [
        ref["evidence_id"] for ref in (evidence_refs or []) if ref.get("evidence_id")
    ]
    gap["motivating_evidence_ids"] = motivating_evidence_ids
    return attach_gap_identity(
        gap,
        evidence_basis="positive_evidence" if motivating_evidence_ids else "absence_of_evidence",
    )


def detect_deterministic_gaps(evidence_objects_by_paper: dict, domain: str) -> list[dict]:
    """Evaluates PATTERNS against a corpus's Evidence Objects. Returns a
    list of gap-candidate dicts shaped identically to
    pipeline/gap_detector.py's LLM output (same keys) so callers can merge
    both lists without special-casing -- the only new key is `source`
    ("deterministic" here, "semantic" on the LLM path) and `pattern_id`.

    `evidence_objects_by_paper`: {paper_id: [evidence_dict, ...], ...} --
    the same shape app.py already builds at Stage 2C.
    """
    if domain not in _APPLICABLE_DOMAINS:
        return []

    all_paper_ids = list(evidence_objects_by_paper.keys())
    if not all_paper_ids:
        return []

    gaps = []
    for pattern in PATTERNS:
        mode = pattern["mode"]

        if mode == "absence":
            if not _corpus_has_type(evidence_objects_by_paper, pattern["evidence_types"]):
                gaps.append(_make_gap(pattern, all_paper_ids))
            continue

        if mode == "no_keyword":
            if not _corpus_has_type(evidence_objects_by_paper, pattern["requires_types"]):
                continue  # nothing to evaluate against -- an extraction gap, not this gap
            text = _corpus_text(evidence_objects_by_paper, pattern["search_types"])
            negation_phrases = pattern.get("negation_phrases")
            if negation_phrases:
                text = _negation_guarded_text(text, negation_phrases)
            if not _any_keyword(text, pattern["keywords"]):
                gaps.append(_make_gap(pattern, all_paper_ids))
            continue

        if mode == "keyword_present":
            hits = _matching_evidence(evidence_objects_by_paper, pattern["search_types"], pattern["keywords"])
            exclude = pattern.get("exclude_keywords")
            if exclude:
                hits = [h for h in hits if not _any_keyword(_norm(h.get("text", "")), exclude)]
            if hits:
                gaps.append(_make_gap(pattern, all_paper_ids, evidence_refs=hits))
            continue

    gaps.extend(_detect_named_limitations(evidence_objects_by_paper))
    return gaps


def _detect_named_limitations(evidence_objects_by_paper: dict) -> list[dict]:
    """The one PRESENCE (not absence) pattern, and the one that's
    per-paper rather than corpus-wide: each distinct self-reported
    Limitation is itself a candidate gap -- the paper already admits it in
    its own words, the highest-confidence, lowest-risk pattern in the
    library. Deduped by exact text so the same limitation phrased
    identically across two papers isn't reported twice."""
    seen_text = set()
    gaps = []
    for paper_id, objs in evidence_objects_by_paper.items():
        for o in objs:
            if o.get("evidence_type") != "Limitation":
                continue
            text = (o.get("text") or "").strip()
            key = text.lower()
            if not text or key in seen_text:
                continue
            seen_text.add(key)
            gap = {
                "title": f"Self-reported limitation: {text[:80]}",
                "description": text,
                "gap_type": _guess_gap_type(text),
                "confidence": o.get("confidence", "medium"),
                "evidence": [f"{paper_id} (Limitation): {text[:300]}"],
                "supporting_papers": [paper_id],
                "missing_connection": text,
                "why_important": "The paper already identifies this as a limitation of its own work.",
                "validation_status": "pending",
                "existing_papers": [],
                "source": "deterministic",
                "pattern_id": "named_limitation_self_reported",
            }
            # Real, always-present evidence_id: this pattern only ever
            # fires on a real Evidence Object `o`, never an absence.
            evidence_id = o.get("evidence_id")
            gap["motivating_evidence_ids"] = [evidence_id] if evidence_id else []
            gaps.append(attach_gap_identity(gap, evidence_basis="positive_evidence"))
    return gaps
