"""Is an extracted parameter a measurement, and is its number even possible?

A real run's "parameters" were mostly survey answers ("62% of respondents agree...") and laboratory
setup values. Opinions are not inputs a disease or survival model can use, and a model that is fed one
reports numbers that look like findings. Every parameter is therefore tagged:

  evidence_kind  "measured" (what a study found about patients, biology or an intervention) or
                 "opinion" (what respondents, experts or participants said they think, prefer or know)
  sanity_issues  impossible values (a probability of 140%, a negative odds ratio, a CI that does not
                 contain its own estimate); such a parameter is demoted to low confidence

Opinion and impossible parameters stay in the table (nothing is silently deleted) but are not counted
toward the sufficiency gate and are never simulated.
"""
from __future__ import annotations

import math
import re

KINDS = ("measured", "opinion")
_OPINION_WORDS = re.compile(
    r"\b(respondents?|survey(?:ed)?|questionnaire|opinion|opined|agree[sd]?|disagree[sd]?|prefer(?:s|red|ence)?|"
    r"perceiv\w+|awareness|aware of|willing(?:ness)?|attitude|belief|believe[sd]?|response rate|"
    r"participants (?:who )?(?:said|stated|reported that they would|felt|thought))\b", re.I)
_SURVEY_TYPES = ("survey_or_questionnaire",)

_PERCENT_CATEGORIES = {"prevalence", "incidence", "proportion", "efficacy", "survival", "sensitivity",
                       "specificity", "transition_probability"}
_RATIO_CATEGORIES = {"odds_ratio", "relative_risk", "hazard_ratio"}
CI_TOLERANCE = 0.02


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def classify_kind(param: dict, study_type: str | None = None) -> tuple[str, str]:
    """(kind, reason). The model's own tag counts; a survey paper's proportions and any text about
    respondents' views are opinions even if the model forgot to say so."""
    said = str(param.get("evidence_kind") or "").strip().lower()
    text = " ".join(str(param.get(k) or "") for k in ("name", "population", "condition", "notes", "source_section"))
    if said == "opinion":
        return "opinion", "tagged as opinion by the extractor"
    if _OPINION_WORDS.search(text):
        return "opinion", "describes what respondents or participants said, not a measurement"
    if study_type in _SURVEY_TYPES and param.get("category") in ("proportion", "prevalence"):
        return "opinion", "a proportion or score from a survey of people's answers"
    return "measured", ""


def sanity_issues(param: dict) -> list[str]:
    """Reasons the number cannot be right (empty when it is plausible)."""
    issues = []
    value = _num(param.get("value"))
    if value is None:
        return ["value is not a finite number"]
    cat, unit = param.get("category"), str(param.get("unit") or "")
    lo, hi = _num(param.get("ci_lower")), _num(param.get("ci_upper"))
    if cat in _RATIO_CATEGORIES and not (0 < value < 100):
        issues.append(f"{cat.replace('_', ' ')} of {value:g} is outside (0, 100)")
    if cat in _PERCENT_CATEGORIES or unit == "percent":
        top = 100.0 if (unit == "percent" or value > 1) else 1.0
        if value < 0 or value > top:
            issues.append(f"{value:g}{'%' if unit == 'percent' else ''} is outside 0 to {top:g}")
    if unit == "per_1000" and not (0 <= value <= 1000):
        issues.append(f"{value:g} per 1000 is outside 0 to 1000")
    if cat == "rate" and value < 0:
        issues.append("a rate cannot be negative")
    if lo is not None and hi is not None:
        if lo > hi:
            issues.append("the confidence interval's lower bound is above its upper bound")
        else:
            span = max(hi - lo, abs(value) * CI_TOLERANCE, 1e-9)
            if value < lo - CI_TOLERANCE * span or value > hi + CI_TOLERANCE * span:
                issues.append("the estimate lies outside its own confidence interval")
    return issues


def annotate_parameters(params: list, study_types: dict | None = None) -> dict:
    """Tags every parameter in place: evidence_kind, kind_reason, sanity_issues (and low confidence when
    impossible). `study_types` is {source paper (title or filename): study type}. Returns counts."""
    counts = {"measured": 0, "opinion": 0, "impossible": 0}
    study_types = study_types or {}
    for p in params:
        if not isinstance(p, dict):
            continue
        stype = study_types.get(p.get("source_paper")) or study_types.get(p.get("source_file"))
        kind, reason = classify_kind(p, stype)
        p["evidence_kind"], p["kind_reason"] = kind, reason
        issues = sanity_issues(p)
        if issues:
            p["sanity_issues"] = issues
            p["confidence"] = "low"
            counts["impossible"] += 1
        else:
            p.pop("sanity_issues", None)
        counts[kind] += 1
    return counts


def is_modelling_input(p: dict) -> bool:
    """A parameter a model may use: a measurement, with a possible value."""
    return p.get("evidence_kind", "measured") != "opinion" and not p.get("sanity_issues")
