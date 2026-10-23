"""Output schemas for the model-backed agents.

A reply that parses as JSON can still have the wrong shape (a missing title, scores out of range, a string where
a list belongs). Each agent's items are checked against the schema below; an item that fails is rejected, counted,
and written to the run's call log, so a drifting model shows up as numbers instead of silent gaps.

The schema language is a small subset of JSON Schema (type, required, properties, enum, min/max, items), plus
`any_required` (at least one key of each group must be present) for fields that have a long and a short name.
"""
from __future__ import annotations

import re

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    # a number, or a string that holds one ("12.5"): models often quote numbers
    "numlike": lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool))
                         or (isinstance(v, str) and re.fullmatch(r"\s*-?\d+(?:[.,]\d+)?\s*", v) is not None),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _problems(value, schema: dict, path: str) -> list[str]:
    errors = []
    kinds = schema.get("type")
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(_TYPES[k](value) for k in kinds):
            return [f"{path}: expected {'/'.join(kinds)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0):
            errors.append(f"{path}: empty")
        if len(value) > schema.get("maxLength", 10 ** 9):
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} is above {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value or value[key] is None:
                errors.append(f"{path}.{key}: missing")
        for group in schema.get("any_required", []):
            if not any(value.get(k) not in (None, "") for k in group):
                errors.append(f"{path}: needs one of {group}")
        for key, sub in schema.get("properties", {}).items():
            if key in value and value[key] is not None:
                errors.extend(_problems(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(_problems(item, schema["items"], f"{path}[{i}]"))
    return errors


_STR = {"type": "string"}
_NONEMPTY = {"type": "string", "minLength": 1}
_STRINGS = {"type": "array", "items": _STR}
_SCORE = {"type": "integer", "minimum": 1, "maximum": 5}
_LEVEL = {"type": "string", "enum": ["high", "medium", "low"]}

SCHEMAS: dict[str, dict] = {
    # Evidence reader: one extracted item
    "reader_item": {
        "type": "object",
        "any_required": [["type", "evidence_type"], ["statement", "text"]],
        "properties": {"type": _NONEMPTY, "evidence_type": _NONEMPTY, "statement": _NONEMPTY, "text": _NONEMPTY,
                       "quote": _STR, "passage": _STR, "confidence": _STR},
    },
    # Gap finders: one candidate gap
    "finder_gap": {
        "type": "object",
        "required": ["title", "description"],
        "properties": {"title": _NONEMPTY, "description": _NONEMPTY, "gap_type": _STR, "confidence": _STR,
                       "evidence_refs": _STRINGS, "supporting_papers": _STRINGS, "missing_connection": _STR,
                       "why_important": _STR},
    },
    # Gap critic: one review
    "critic_review": {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": ["string", "integer"]}, "novelty": _SCORE, "importance": _SCORE,
                       "feasibility": _SCORE, "verdict": {"type": "string", "enum": ["keep", "merge", "drop"]},
                       "merge_into": {"type": ["string", "null"]}, "reason": _STR, "critique": _STR,
                       "sharpened_title": {"type": ["string", "null"]}},
    },
    # Literature scout: planner row and assessor verdict
    "scout_plan_row": {
        "type": "object",
        "required": ["id", "queries"],
        "properties": {"id": {"type": ["string", "integer"]}, "queries": _STRINGS},
    },
    "scout_assessment": {
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"type": "string", "enum": ["open", "partial", "solved"]}, "reasoning": _STR,
                       "relevant": {"type": "array"}},
    },
    # Proposal generator and reviewer
    "proposal": {
        "type": "object",
        "required": ["title", "problem_statement"],
        "properties": {"title": _NONEMPTY, "problem_statement": _NONEMPTY, "methodology": _STR, "novelty": _STR,
                       "builds_on": _STRINGS, "addresses_gap": _STR, "addresses_gap_ref": _STR,
                       "expected_contribution": _STR, "suggested_experiments": _STRINGS,
                       "potential_datasets": _STRINGS, "confidence": _STR},
    },
    "proposal_review": {
        "type": "object",
        "required": ["index"],
        "properties": {"index": {"type": "integer", "minimum": 0}, "specificity": _SCORE, "novelty": _SCORE,
                       "feasibility": _SCORE, "impact": _SCORE,
                       "verdict": {"type": "string", "enum": ["accept", "revise", "reject"]},
                       "issues": _STRINGS, "required_changes": _STR, "reason": _STR},
    },
    # Parameter extractor: one parameter
    "parameter": {
        "type": "object",
        "required": ["name", "value"],
        "properties": {"name": _NONEMPTY, "value": {"type": "numlike"},
                       "ci_lower": {"type": ["numlike", "null"]}, "ci_upper": {"type": ["numlike", "null"]},
                       "category": _STR, "unit": _STR, "population": _STR, "condition": _STR, "source_paper": _STR,
                       "confidence": _STR, "is_derived": {"type": "boolean"},
                       "evidence_kind": {"type": "string", "enum": ["measured", "opinion"]}},
    },
    # Council chair replies
    "council_consensus": {
        "type": "object",
        "required": ["consensus"],
        "properties": {"consensus": _STR, "key_points": _STRINGS, "disagreements": _STRINGS, "confidence": _STR,
                       "caveats": _STRINGS},
    },
    "council_model_choice": {
        "type": "object",
        "required": ["selected_model"],
        "properties": {"selected_model": _NONEMPTY, "rationale": _STR, "scenarios": _STRINGS,
                       "key_parameters_to_use": _STRINGS, "parameters_to_flag": _STRINGS, "confidence": _STR},
    },
    "council_insights": {
        "type": "object",
        "required": ["novel_finding"],
        "properties": {"novel_finding": {"type": "object", "required": ["title", "claim"],
                                         "properties": {"title": _NONEMPTY, "claim": _NONEMPTY,
                                                        "evidence_chain": _STRINGS, "confidence": _STR}},
                       "clinical_insights": _STRINGS, "research_insights": _STRINGS, "key_uncertainties": _STRINGS,
                       "actionable_next_steps": _STRINGS, "limitations": _STRINGS},
    },
}


def check(agent: str, value) -> list[str]:
    """The problems with `value` as an item of `agent`'s output; an empty list means it is valid."""
    return _problems(value, SCHEMAS[agent], agent)


def log_errors(client, agent: str, errors: list[str]) -> None:
    """Write schema problems to the client's call log, when it has one."""
    log = getattr(client, "call_log", None)
    record = getattr(log, "record_schema_error", None)
    if callable(record):
        record(stage=getattr(client, "current_stage", "") or "", agent=agent, detail="; ".join(errors)[:600])


def keep_valid(agent: str, items, client=None) -> tuple[list, int]:
    """(valid items, number rejected). Rejected items are written to the call log with the reasons."""
    kept, rejected = [], 0
    for item in items or []:
        errors = check(agent, item)
        if errors:
            rejected += 1
            log_errors(client, agent, errors)
        else:
            kept.append(item)
    return kept, rejected


def valid_or_empty(agent: str, value, client=None):
    """`value` if it is valid for `agent`, else None (the problems are logged)."""
    errors = check(agent, value)
    if errors:
        log_errors(client, agent, errors)
        return None
    return value
