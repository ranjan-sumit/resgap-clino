"""Additive index over the existing, unmodified evals/benchmarks/v1 and v2
fixtures -- does NOT rewrite either format (v1 stays immutable/heavyweight,
v2 stays lightweight/evolving). Maps each real case_id to which of Epic
4.3's metrics it feeds. Case types/filenames confirmed against the actual
files on disk, not assumed.

Full 10-case-type coverage and v1/v2 format unification are explicitly
deferred (09-epics-and-stories.md's Epic 4.3 note) -- this index only
covers what already exists today, and most cases honestly feed no metric
yet (`feeds: []`), which is a real, stated gap, not silently hidden.
"""

# NOTE: v1's on-disk filenames do not always match the case's internal
# case_id field (a pre-existing inconsistency in the fixtures themselves,
# confirmed by reading all 4 files -- e.g. case_id "corpus-reference-
# contamination-espanol" lives in "case-reference-contamination-espanol.json",
# dropping the "corpus-" prefix). Fixing that is part of the deferred v1/v2
# format-unification work, not this pass -- so each entry below records its
# real on-disk filename explicitly rather than assuming a naming convention.
CASE_TYPE_INDEX = {
    "v1": {
        "corpus-reference-contamination-espanol": {
            "case_type": "unrelated_references_title_collision",
            "feeds": ["corpus_contamination_rate"],
            "filename": "case-reference-contamination-espanol.json",
            # The known off-topic reference's DOI, used to check whether it
            # survives filter_and_dedupe_references() -- all 3 fixture_references
            # entries in this case share this same DOI (a real duplicate-record
            # contamination instance, not 3 distinct off-topic refs).
            "contaminated_doi": "10.1353/hpn.2017.0025",
        },
        "corpus-reference-duplicate-doi": {
            "case_type": "duplicate_references_same_paper_diff_providers",
            "feeds": ["reference_resolution_precision", "reference_recall"],
            "filename": "case-reference-duplicate-doi.json",
            # 3 real duplicate groups (fixture_duplicate_groups), 2 DOI-
            # identical records each -- real implicit ground truth for
            # reference-resolution precision/recall.
            "duplicate_group_count": 3,
        },
        "corpus-truncated-doi": {
            "case_type": "malformed_citations",
            "feeds": [],
            "filename": "case-truncated-doi.json",
        },
        "zero-gap-silent-fabrication": {
            "case_type": "intentionally_false_or_fabrication_robustness",
            "feeds": ["extraction_completeness"],
            "filename": "case-zero-gap-silent-fabrication.json",
        },
    },
    "v2": {
        "known-closed-adhd-heritability": {
            "case_type": "known_closed_gaps",
            "feeds": ["false_novelty_rate"],
            "filename": "case-known-closed-adhd-heritability.json",
        },
        "known-open-asd-adhd-causal-mechanism": {
            "case_type": "known_genuine_research_gaps",
            "feeds": ["gap_precision"],
            "filename": "case-known-open-asd-adhd-causal-mechanism.json",
        },
        # Epic 4.3 Bucket C (2026-08-24): 3 new real, cited, dated cases --
        # see each file's own "verification" block for sources.
        "fabricated-reelin-subplate-adhd-subtype": {
            "case_type": "intentionally_false_or_fabrication_robustness",
            "feeds": ["gap_precision"],
            "filename": "case-fabricated-reelin-subplate-adhd-subtype.json",
        },
        "ambiguous-methylphenidate-response-comorbid-autism-adhd": {
            "case_type": "ambiguous_gaps",
            # Deliberately NOT wired into gap_precision: that metric's
            # ground truth is a clean genuinely-novel/not-novel binary
            # (see evals/regression/metrics.py's _GAP_PRECISION_GROUND_
            # TRUTH), and a genuinely-contested question is neither --
            # folding it in would silently conflate "not confirmed novel"
            # with "confirmed fabricated," muddying what the number means.
            # This case is a real, valuable regression fixture for the
            # CONTESTED/PARTIALLY_OPEN recognition path itself; it just
            # doesn't feed a numeric §3 metric yet.
            "feeds": [],
            "filename": "case-ambiguous-methylphenidate-response-comorbid-autism-adhd.json",
        },
        "contradictory-pair-amygdala-volume-autism": {
            "case_type": "contradictory_research_pairs",
            "feeds": ["contradiction_recall", "retrieval_recall"],
            "filename": "case-contradictory-pair-amygdala-volume-autism.json",
        },
    },
    # v3 (Epic 4.3 Bucket B, 2026-08-24): declared as v1's successor format
    # -- v1's MANIFEST.json is immutable=true, so these new structural
    # fixtures cannot be added there per 07-evaluation-architecture.md §2.
    "v3": {
        "title-author-year-fallback": {
            "case_type": "duplicate_references_same_paper_diff_providers",
            "feeds": ["reference_resolution_precision", "reference_recall"],
            "filename": "case-title-author-year-fallback.json",
        },
        "title-only-quarantine": {
            "case_type": "malformed_citations",
            "feeds": [],
            "filename": "case-title-only-quarantine.json",
        },
        "unknown-title-collision": {
            "case_type": "unrelated_references_title_collision",
            "feeds": [],
            "filename": "case-unknown-title-collision.json",
        },
        "missing-abstract": {
            "case_type": "missing_abstracts",
            "feeds": [],
            "filename": "case-missing-abstract.json",
        },
        "parser-failure": {
            "case_type": "parser_failures",
            "feeds": [],
            "filename": "case-parser-failure.json",
        },
    },
}


def cases_feeding(metric_name: str) -> list[tuple[str, str, str]]:
    """Returns [(version, case_id, filename), ...] for every case that
    feeds the named metric, across both v1 and v2."""
    out = []
    for version, cases in CASE_TYPE_INDEX.items():
        for case_id, info in cases.items():
            if metric_name in info["feeds"]:
                out.append((version, case_id, info["filename"]))
    return out
