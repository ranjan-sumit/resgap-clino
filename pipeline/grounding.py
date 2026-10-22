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


# ── named entities ────────────────────────────────────────────────────────────────────────
# A claim can name a gene, drug or marker that no paper mentions (a model's own knowledge slipping in
# as if it were a finding). Two shapes are checked, because they are what such names look like:
# acronyms and gene symbols (CFTR, IL-8, FEV1) and drug-style names (ivacaftor, adalimumab).
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)?\b")
_DRUG_RE = re.compile(r"\b[a-z]{3,}(?:mab|nib|caftor|cept|tide|vir|stat|olol|pril|sartan|azole|mycin|cillin|gliptin|glutide)\b")
_COMMON_ACRONYMS = frozenset({
    "DNA", "RNA", "MRNA", "PCR", "ICU", "USA", "UK", "EU", "WHO", "FDA", "EMA", "NHS", "CI", "OR", "RR", "HR", "SD",
    "AI", "ML", "CT", "MRI", "ECG", "BMI", "II", "III", "IV", "PDF", "AND", "NOT", "THE", "FOR", "ALL", "NO", "VS",
    "IL", "TNF", "ID", "OK", "PH", "UV", "CO2", "O2", "ATP", "GDP", "QOL",
})
_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def corpus_words(*sources) -> set:
    """Every lower-case word (and hyphenated term) in the given sources: what the papers actually say."""
    text = " ".join(s if isinstance(s, str) else json.dumps(s, ensure_ascii=False, default=str) for s in sources)
    low = text.lower()
    words = set(_WORD_RE.findall(low))
    words |= {w.replace("-", "") for w in words if "-" in w}
    return words


def entity_candidates(text: str) -> list:
    """Acronym-style and drug-style names in `text`, as written, in order, without repeats."""
    out = []
    for m in _ACRONYM_RE.finditer(text or ""):
        tok = m.group(0)
        if tok.upper() in _COMMON_ACRONYMS or (len(tok) < 3 and not any(c.isdigit() for c in tok)):
            continue
        if tok not in out:
            out.append(tok)
    for m in _DRUG_RE.finditer(text or ""):
        if m.group(0) not in out:
            out.append(m.group(0))
    return out


def unsupported_entities(text: str, known_words: set) -> list:
    """Named entities in `text` that appear in none of the papers (compared case-insensitively, hyphens ignored)."""
    out = []
    for ent in entity_candidates(text):
        low = ent.lower()
        if low not in known_words and low.replace("-", "") not in known_words:
            out.append(ent)
    return out


def annotate_claims(items: list, fields: tuple, known: set, known_words: set | None = None) -> int:
    """Adds `unsupported_numbers` to every dict in `items` whose `fields` text contains ungrounded
    effect-size numbers and, when `known_words` is given, `unsupported_entities` for named entities
    no paper mentions; lowers a "high" confidence to "medium" for either. Returns how many were flagged."""
    flagged = 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        found, ents = [], []
        for f in fields:
            text = str(it.get(f) or "")
            found += unsupported_numbers(text, known)
            if known_words is not None:
                ents += unsupported_entities(text, known_words)
        if found:
            it["unsupported_numbers"] = sorted(set(found))
        if ents:
            it["unsupported_entities"] = sorted(set(ents))
        if found or ents:
            it["speculative"] = True            # rests on something the papers do not contain
            if it.get("confidence") == "high":
                it["confidence"] = "medium"
            flagged += 1
    return flagged
