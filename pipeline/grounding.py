"""
Number grounding for generated claims.

The Lab's discovery and insight agents were told to state claims "by [estimate]", so a real run
reported that stress hormones "will increase IL-8 by >35% and bacterial growth >2-fold" -- figures
that appear in no paper. The prompts no longer ask for them, and this module checks the output
anyway: any effect-size style number (a percentage, a fold-change) in a generated claim that is not
found in the papers' own text is listed so it can be shown as ungrounded.

Only effect-size style numbers are checked. Study-design numbers a proposal legitimately invents
(N=16, a 72-hour exposure) are not claims about what the papers found.
"""
import json
import re

_EFFECT_RE = re.compile(r"(?:[<>≥≤~]\s*)?(\d+(?:[.,]\d+)?)\s*(?:%|percent\b|-?\s?fold\b|×|x\b)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _norm(n: str) -> str:
    n = n.replace(",", ".")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    return n


def corpus_numbers(*sources) -> set:
    """Every number appearing anywhere in the given sources (strings, dicts, lists, nested)."""
    text = " ".join(s if isinstance(s, str) else json.dumps(s, ensure_ascii=False, default=str) for s in sources)
    return {_norm(n) for n in _NUMBER_RE.findall(text)}


def effect_size_numbers(text: str) -> list:
    """The effect-size style numbers in `text` ("35%", ">2-fold", "1.5 x"), in order, as written."""
    return [m.group(0).strip() for m in _EFFECT_RE.finditer(text or "")]


def unsupported_numbers(text: str, known: set) -> list:
    """Effect-size numbers in `text` that appear nowhere in `known` (a corpus_numbers() set)."""
    out = []
    for m in _EFFECT_RE.finditer(text or ""):
        if _norm(m.group(1)) not in known:
            out.append(m.group(0).strip())
    return out


def annotate_claims(items: list, fields: tuple, known: set) -> int:
    """Adds `unsupported_numbers` (a list) to every dict in `items` whose `fields` text contains
    ungrounded effect-size numbers, and lowers a "high" confidence to "medium" for them.
    Returns how many items were flagged."""
    flagged = 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        found = []
        for f in fields:
            found += unsupported_numbers(str(it.get(f) or ""), known)
        if found:
            it["unsupported_numbers"] = sorted(set(found))
            if it.get("confidence") == "high":
                it["confidence"] = "medium"
            flagged += 1
    return flagged
