# Audit 22a: reference extraction (Stage 1B)

**Input:** the three cystic-fibrosis review papers in `data/projects/cystic-fibrosis-review-6bcc0b4b` (MDPI numbered style, Elsevier
`[n]` style, Vancouver `[n]` style with DOIs), real Crossref / OpenAlex / PubMed / Semantic Scholar calls, and real Gemini
(`gemini-3.5-flash-lite`) for the model stage. Dated 2026-10-23.

## Findings and fixes

| # | Finding (measured) | Effect | Fix |
|---|---|---|---|
| 1 | The text extractor (pdfplumber, default spacing) **lost every space** in one paper: 143 of 450 words in its reference list, 43 of 92 in its opening, were 18+ letters long ("Rowe,S.M.;Miller,S.;Sorscher,E.J.CysticFibrosis.N.Engl.J.Med.2005"). Spacing 1.5 fixed it with no change on the other two papers. | The paper's full text (wiki, parameters, references) was unusable. The evidence reader was unaffected because it reads the structural parser's text. | Spacing 1.5, with a tighter retry when words still run together (`pipeline/pdf_parser.py`). |
| 2 | The entry splitter treated any `12.` as a new entry, so page numbers started entries: 95 "entries" for 94 real ones in one paper, 137 for 72 in another, with titles like `,352,1992–2001.[CrossRef][PubMed]`. | Junk entries searched for as titles. | Only the next number in the sequence 1, 2, 3 … is a boundary (`[n]`, `(n)` and `n.` styles). Counts are now 94 / 37 / 72. |
| 3 | Ligatures ("ﬁ"), words broken at line ends ("com- plementary") and DOIs split by a line break or space (`doi.org/ 10.3389/…`, `10.1186/s12967-017- 1193-9`). | Titles and DOIs that no lookup could match. | `clean_reference_text`. |
| 4 | **OpenAlex and PubMed title searches took the first hit without checking the title.** A query of "Pharmacol" returned the journal *Mol. Pharmacol.*; "ECFS Patient Registry" returned an unrelated paper with a DOI and abstract. PubMed returned a different paper's title in 7 of 12 test cases. | A wrong paper's title and abstract attached to a reference (Tier 2). | All title searches now require title similarity of at least 0.85 (best of several hits). |
| 5 | Semantic Scholar's title search answered HTTP 429 every time without a key (12 of 12); lookup by DOI worked. | One provider in the chain was dead. | The Semantic Scholar key from the run options is now passed to this stage; the chain does not rely on it. |
| 6 | Guessed titles such as "Pharmacol", "Care Med", "Available online" were searched for. | Wrong matches (see 4) or nothing. | A title must look like a title (3+ words, not "Available online …"); otherwise the whole citation is sent to Crossref's bibliographic search and a hit is kept only if its title and year appear in the citation. |
| 7 | DOI-only records were placed ahead of the paper's own entries, so a cap of N references took the first DOIs, not the first references, and lost the citation text. Crossref rarely has abstracts. | 10 of 36 references had an abstract. | The paper's entries come first, in order; leftover DOIs last. A missing abstract is filled from OpenAlex by DOI. 22 of 36 now have one. |
| 8 | The model saw only the first 6,000 characters of the reference text, and structured and rule-based copies of the same entry were both kept. | About 35 of 72 references reached the model; duplicates. | The model is given the numbered entries it will be asked about; entries it parsed are not repeated. Its replies are checked against a schema. |
| 9 | Lookups were sequential: up to 7 calls of 2–5 s per reference. | Slow. | Three lookups run side by side; results keep the paper's order. 36 references in about 110 s. |
| 10 | Crossref titles contain markup (`<i>CFTR</i>`). | Shown as raw markup. | Tags removed. |

Cached reference matches from before this change may belong to a different paper, so `REFERENCE_STAGE_VERSION` was bumped to 2.

## After the fixes (same three papers, 12 references each, no model)

- 36 references in 111 s; 22 Tier 2 with an abstract, 14 title only; none unresolved by error.
- Of 30 Tier 2 references, 29 had a title that appears in their own citation (the other is the real, two-word title "Cystic fibrosis").
- With the model on two papers (20 references each): 38 references, 25 with an abstract, authors present, 0 schema errors.

## Still open

- References are capped (default 30 per paper), so only the first 30 of 72–94 are looked up.
- A very short title ("Cystic fibrosis") cannot be verified against a citation and is matched only by DOI or by title search.
- Entries with no DOI and a title Crossref does not return stay Tier 3 (a citation string, not "Unknown").
- Page-footer text between two entries (a journal name and page count) stays inside the earlier entry.
- The rule-based parser does not extract authors or the journal; only the model stage does.
