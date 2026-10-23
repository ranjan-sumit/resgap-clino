# Audit 22c: Gap Challenger (Stage 5b) and its NVIDIA rerank dependency

**Input:** the eight gaps of the latest stored real run (cystic-fibrosis airway-chip papers); four were challenged with real Europe PMC /
Semantic Scholar / arXiv searches, real Gemini for the query planner and the judge, and the NVIDIA key from `.env`. Dated 2026-10-23.

## Findings and fixes

| # | Finding (measured) | Effect | Fix |
|---|---|---|---|
| 1 | **The NVIDIA reranker was retired (HTTP 410 Gone).** It is the fourth NVIDIA model in this codebase to be retired; NVIDIA's model list no longer contains any reranker. The step failed silently, so `rerank_used` was always false and nothing showed it. | A pipeline stage that never ran, recorded in every manifest as if it had (`reranker_version`, `embedding_model_version`). | Ranking is now computed locally (`pipeline/relevance_ranking.py`, "token-overlap-v1": shared words weighted by rarity, plus shared two-word phrases). Nothing is sent anywhere. The manifest records the ranker actually used and no embedding model. |
| 2 | The reranker took `NVIDIA_API_KEY` from the environment whenever it was set, and the app also passed the active model key as the NVIDIA key. | Gap text and candidate abstracts went to a third party, and the key of another provider was sent to NVIDIA, without anyone choosing it. | Both removed. The challenger sends nothing to any provider except the chosen model. |
| 3 | The searches were the gap's own title (up to 120 characters) sent to Semantic Scholar and arXiv. They returned **0, 2, 0 and 2 candidates** for gaps the literature check found 5 papers for. arXiv is not a biomedical source. | "Searched, nothing found" was reported as **OPEN** with full coverage when the query had simply found nothing. | The challenger uses the literature check's query planner (three short keyword queries), Europe PMC and Semantic Scholar, with arXiv only for machine-learning corpora. Candidate pools are now 27–36. |
| 4 | Records titled "Papers", "Abstract" and similar reached the judge. | The judge spent attention on junk. | Section-name and very short titles are discarded; duplicates merge by DOI or title. |
| 5 | When Semantic Scholar answered 429, coverage was 0.5 and the decision table returned INSUFFICIENT_EVIDENCE **before looking at the candidates**, even if papers directly did the work. | A gap that was clearly done stayed unresolved. | Absence still needs full coverage (OPEN / PARTIALLY_OPEN stay INSUFFICIENT_EVIDENCE below it), but two or more direct, high-confidence papers with no contradiction now give LIKELY_CLOSED even on a partial search; never CLOSED. |
| 6 | After a refusal, every remaining query still waited out Semantic Scholar's retry (about 8 s each). | A gap took 25-45 s, mostly waiting. | The rest of that gap's Semantic Scholar queries are skipped after the first refusal (the literature check benefits too). |
| 7 | Gaps were challenged one after another. | Eight gaps took several minutes. | Three at a time. |

## Result on the same gaps

- Candidate pools 27–36 instead of 0–2; the judge saw ten ranked, de-duplicated records per gap.
- The three airway-chip gaps stayed OPEN, now with 27–34 candidates examined and none judged relevant; the literature check agrees ("open").
- The mental-health gap went from INSUFFICIENT_EVIDENCE (search refused) to CLOSED with three direct, high-confidence papers (the literature check said "partial": the two disagree and the judged papers are listed on the gap for a person to read).

## Still open

- Two independent validators (the literature check and the challenger) now use the same searches and can disagree; the report shows both. Merging them into one is a design decision, not a fix.
- The judge sees titles and abstracts truncated to 600 characters; a paper that does the work only in its methods can be marked not relevant.
- The ranking is lexical: a paper using different words for the same idea ranks lower. With ten candidates judged this matters little, but a larger pool would need an embedding model (which would be a new data flow to approve).
- Europe PMC's biomedical coverage is strong; outside biomedicine the pool depends on Semantic Scholar, which is rate-limited without a key.
