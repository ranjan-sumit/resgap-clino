---
name: 'DOI disambiguation — real-data finding, Story 1.1.3'
type: finding
created: '2026-08-21'
---

# DOI disambiguation: position beats length as a signal

While validating `pipeline/extraction_reconciler.py`'s DOI reconciliation against `Data-17072026/AuDHD_1.pdf` (real data, not a synthetic fixture), PyMuPDF and Docling extracted two genuinely **different**, both-valid DOIs from the same paper:

- **PyMuPDF** found `10.1038/s41598-026-35440-6` at char 4,402 of 53,417 (4.4M mark) — the paper's own front-matter/header DOI.
- **Docling** found `10.17605/OSF.IO/DZVMG` at char 47,859 of 65,083 (73% mark), in the sentence *"Scripts and information about the R packages used for the analyses are available at: https://doi.org/10.17605/OSF.IO/DZVMG."* — a linked OSF data/code repository, not the paper's own identity.

Docling's extraction did not capture the paper's own DOI at all (likely missed in header/layout parsing) — itself a useful, real completeness gap that motivates keeping PyMuPDF as an independent cross-check rather than trusting Docling alone, even though Docling's raw text was longer overall (65,083 vs. 53,417 chars).

**An initial implementation used "prefer the longer DOI string" to resolve this disagreement** and happened to get the right answer here (27 chars vs. 21), but for the wrong reason — string length has no principled relationship to "which DOI belongs to the paper itself." The fix (see `pipeline/extraction_reconciler.py`'s `reconcile_paper`) instead uses **match position as a fraction of the source text's length**: a paper's own DOI reliably appears very early (front matter), while an unrelated DOI mentioned in the body (data availability, funding, code repository) appears later. This is now the binding disambiguation rule for two genuinely different (non-prefix-related) DOI candidates — length is used only for the separate, distinct case where one candidate is literally a truncated prefix of the other (see `test_truncated_doi_in_one_source_recovered_from_the_other`).

Test coverage: `tests/test_extraction_reconciler.py::DoiReconciliationTests::test_two_genuinely_different_dois_prefers_earliest_position`.
