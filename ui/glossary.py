"""Plain-language definitions for the words the app uses as labels.

Every status, badge and technical term shown to a reader has an entry here; the app shows it as a hover
hint (`title`) next to the label and lists all of them in the Glossary on the Overview.
"""
from __future__ import annotations

GLOSSARY: dict[str, str] = {
    # gap status: has published work already covered it?
    "open": "No published paper was found that already does this.",
    "partial": "Related work exists, but not this exact thing, so the gap is only partly covered.",
    "solved": "A published paper already does what this gap proposes.",
    "pending": "Not yet checked against the published literature.",
    "unverified": "The literature search was unavailable, so this gap could not be checked.",
    "not checked": "The literature search was unavailable, so this gap could not be checked.",
    # deep validation (Gap Challenger)
    "challenger: open": "After a deeper search, still no paper found that closes this gap.",
    "partially open": "After a deeper search, some related work covers part of the gap.",
    "contested": "Published papers disagree about whether this is already settled.",
    "likely closed": "A deeper search found strong signs that this has already been done.",
    "closed": "A deeper search found work that clearly covers this gap.",
    "insufficient evidence": "The deeper search did not look widely enough to decide either way.",
    # evidence and quality
    "evidence item": "A statement a paper makes (a result, a limitation, a method) with the passage it rests on.",
    "quote rate": "The share of evidence items backed by a word-for-word passage found in the paper.",
    "verified quote": "A passage the reader quoted and the app found, letter for letter, in the paper's own text.",
    "study type": "The kind of study a paper is (clinical trial, review, survey, lab study ...), which decides what can be said about it.",
    "paper coverage": "The share of uploaded papers that went through every stage and contributed.",
    "unsupported numbers": "Percentages or fold-changes in a generated claim that appear in none of the papers.",
    "speculative": "A generated claim that names things or numbers the papers do not contain.",
    # graph
    "orphan signals": "Concepts that appear in only one paper with few links. They hint at unexplored areas; they are not errors.",
    "communities": "Groups of closely related concepts in the knowledge graph.",
    "grounded": "Every relationship cites a quoted passage that states it.",
    "leaf share": "The share of graph concepts connected to only one other concept.",
    # lab
    "measured": "A value a study found about patients, biology or an intervention.",
    "opinion": "What respondents or experts said they think or prefer: kept, but never used to simulate.",
    "simulation skipped": "The papers do not contain enough usable numbers to simulate anything honestly.",
    "refused": "An algorithm that needs inputs the papers do not provide, so it was not run.",
    "coverage": "How well the extracted parameters cover what a model needs (0-10).",
    # runs
    "completed": "The run finished all its stages.",
    "quality check failed": "Extraction quality was too low, so gap analysis was skipped.",
    "no manifest": "This run was saved without its technical record.",
    "archived": "Hidden from lists; nothing was deleted.",
    "token cap": "A safety limit on how much text the models may process in one run.",
    "fallback model": "A second model that answered when the chosen one failed.",
    "agreement with the previous run": "The share of distinct gaps found by both this run and an earlier run on the same papers.",
    "critic": "The model that scores and ranks candidate gaps.",
    "reviewer": "The model that scores and critiques the proposals.",
}


def definition(term: str) -> str:
    return GLOSSARY.get((term or "").strip().lower(), "")


def completed_with_warnings(label: str) -> bool:
    return label.lower().startswith("completed")


def lookup(label: str) -> str:
    """The definition for a label, tolerating variants like 'Completed · 2 warning(s)'."""
    low = (label or "").strip().lower()
    if low in GLOSSARY:
        return GLOSSARY[low]
    if low.startswith("completed"):
        return GLOSSARY["completed"]
    return ""
