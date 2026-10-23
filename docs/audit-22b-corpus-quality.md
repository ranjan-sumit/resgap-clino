# Audit 22b: Corpus Quality Engine (2B) and canonical reference resolution (1C)

**Input:** the same three cystic-fibrosis review papers, run through the structural cross-check, the reconciler, the
completeness score, the gate and reference resolution with the engine switched on (it is off by default). Real Gemini wiki
pages, real Crossref lookups for the DOI check. Dated 2026-10-23.

## What was right

- The reconciled **DOI was the paper's own on all three**, confirmed by looking each up in Crossref and comparing titles.
- The gate passed all three papers, which is the correct verdict for well-extracted papers.

## Findings and fixes

| # | Finding | Effect | Fix |
|---|---|---|---|
| 1 | Abstract, introduction and conclusion were permanently "not extracted" ("no extraction path exists"), although the papers have them and the parser sees their headings. | Every paper scored an identical 8 of 16, whatever was in it; the gate could not tell a complete extraction from a poor one. | Found from the paper's own headings and abstract label (including the letter-spaced "A B S T R A C T" and "Abstract:" forms). A missing section is `empty`, not "not extracted". |
| 2 | The "achievable ceiling" was 11 of 16, but `models_interventions` was also always missing, so the real ceiling was 10. A perfect paper could never reach 100%. | Gate arithmetic off by one field. | The ceiling is now derived from the fields that can never be found (authors, metrics, models/interventions): 13. A paper with everything findable scores 100%. |
| 3 | All three papers have tables (Table 1 on p. 8; Tables 1–3 on pp. 5, 7, 11) but both table detectors found 0, because the tables have no ruling lines. | "tables: empty" for papers with tables. | A "Table N" caption with no detected cells now counts as present, at low confidence, source "caption only". Real borderless-table extraction is not attempted (see below). |
| 4 | Every paper was credited with the corpus-wide reference count, so a paper whose reference list failed to parse still scored "references present". | Hides a per-paper failure. | Each paper's own detected entry count is used. |
| 5 | The reference funnel counted title-only records as "resolved" (36 of 36) and "unresolved" was always 0, though 14 references were found by no lookup. | The funnel overstated success. | `resolved` = found by a lookup; the references nothing found are `unresolved` (5 in this run). New diagnostics: `resolved_no_abstract`, `unmatched`. |
| 6 | The reconciler took the **first DOI anywhere in the text** as the paper's own. A paper with no DOI of its own (a preprint, a thesis) would be given the first cited paper's DOI. | Wrong identity. | Only a DOI in the front matter (first 6,000 characters or 25%) can be the paper's own. A later DOI stays listed as a candidate, flagged `front_matter: false`, and the paper is marked for model recovery. |
| 7 | 7 of 36 references (Tier 3, title and year, no author) were quarantined and dropped from later stages, including real references such as "Rowe … Cystic Fibrosis. N Engl J Med 2005". | A real reference list shrank by about 20%. | A title of 3+ words with a year is accepted as the reference as written (level `title_year`); weaker ones are still quarantined. |
| 8 | A failure of the second parser was swallowed silently. | The paper scored low with no explanation. | A warning names the paper. |

## After the fixes (same papers)

Per-paper achievable completeness 0.92 / 0.77 / 0.92 (before: 0.73 for all three); corpus 0.87; DOI resolution 86%; gate PASS;
36 of 36 references kept, 30 VERIFIED and 6 ACCEPTED; funnel: 203 detected, 30 resolved, 5 unresolved in the 36 looked up.

## Still open

- Borderless tables are not extracted as tables. Their text is in the paper (the evidence reader sees it as passages), but the
  rows and columns are lost. A caption-guided table reader is a project of its own.
- Authors, metrics and models/interventions are not extracted by anything, so they never count (and never penalise).
- Metrics and models/interventions could be filled from the evidence reader's output, but evidence is extracted after this stage.
- The gate thresholds (35% fail, 60% pass) were not recalibrated; with real sections counted they are easier to pass.
