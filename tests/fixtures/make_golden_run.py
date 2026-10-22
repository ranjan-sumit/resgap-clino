"""Synthetic fixtures: a 3-paper run in the current schema and a legacy run
in the old schema (no paper_profiles / trace / supplementary_gaps).

All text is invented -- nothing here is copyrighted material.
"""
from __future__ import annotations

import copy

import utils.database as db

_PAPERS = [
    ("Alpha trial of drug X", "alpha.pdf"),
    ("Beta cohort study of drug X", "beta.pdf"),
    ("Gamma review of drug X", "gamma.pdf"),
]


def golden_results() -> dict:
    papers = [{"title": t, "filename": f, "sections": {"Methods": "Synthetic text."}}
              for t, f in _PAPERS]
    gaps = [
        {"id": "G1", "gap_id": "g1", "motivating_evidence_ids": ["e1", "e3"], "title": "No long-term follow-up", "description": "Follow-up under 6 months.",
         "papers": [_PAPERS[0][0], _PAPERS[1][0]], "rank": 1, "status": "open",
         "evidence": [{"paper": _PAPERS[0][0], "quote": "Follow-up was 3 months.", "page": 4}]},
        {"id": "G2", "title": "Single-centre data", "description": "Only one site enrolled.",
         "papers": [_PAPERS[1][0]], "rank": 2, "status": "open", "evidence": []},
    ]
    proposals = [{"gap_id": "G1", "title": "Two-year extension cohort",
                  "objective": "Measure durability.", "status": "reviewed"}]
    return {
        "context": {"domain": "synthetic", "run_name": "golden"},
        "papers": papers,
        "gaps": gaps,
        "proposals": proposals,
        "paper_profiles": {f: {"study_type": "rct"} for _, f in _PAPERS},
        "evidence_objects": {
            "alpha.pdf": [
                {"evidence_id": "e1", "evidence_type": "Limitation", "paper_id": "alpha.pdf", "confidence": "high",
                 "text": "Follow-up was limited to three months.",
                 "provenance": {"page": 4, "section": "Discussion", "quote": "Follow-up was 3 months."}},
                {"evidence_id": "e2", "evidence_type": "Result", "paper_id": "alpha.pdf", "confidence": "medium",
                 "text": "Lung function improved by 5 points.",
                 "provenance": {"page": None, "section": "Results", "quote": None}},
            ],
            "beta.pdf": [
                {"evidence_id": "e3", "evidence_type": "StudyDesign", "paper_id": "beta.pdf", "confidence": "high",
                 "text": "A single-centre cohort of 80 patients.",
                 "provenance": {"page": 2, "section": "Methods", "quote": "We enrolled 80 patients at one centre."}},
            ],
            "gamma.pdf": [],
        },
        "supplementary_gaps": [],
        "pipeline_trace": [
            {"stage": "Stage 1 — PDF Parse", "inputs": "3 PDFs", "outputs": "9,000 chars extracted", "status": "✅"},
            {"stage": "Stage 2 — LLM Wiki", "inputs": "3 papers", "outputs": "3 pages", "status": "⚠️"},
        ],
        "models": {"roles": {"extraction": {"provider": "gemini", "model": "gemini-3.5-flash-lite"}}},
    }


def legacy_results() -> dict:
    """Old schema: only context/papers/gaps/proposals."""
    r = copy.deepcopy(golden_results())
    for k in ("paper_profiles", "supplementary_gaps", "pipeline_trace", "models"):
        r.pop(k)
    return r


def seed_run(results: dict | None = None, name: str = "Golden run",
             project_id: str | None = None) -> str:
    """Save a run into the (test) database and return its id."""
    db.init_db()
    return db.save_run(name, results if results is not None else golden_results(),
                       project_id=project_id)
