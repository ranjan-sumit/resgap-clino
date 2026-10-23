# Audit 22f: graph snapshots and diffs

**Input:** the four graph snapshots in the stored database; the diff of "Run 3" and its agentic rerun (the same three papers, 24 and 25
entities, 25 and 26 relationships); a check of every table that is keyed by a run. Dated 2026-10-23.

## Findings and fixes

| # | Finding (measured) | Effect | Fix |
|---|---|---|---|
| 1 | **Deleting a run left most of what the database holds for it.** `delete_run` removed the run, its papers and (by cascade) its files, feedback and stored blobs. The graph snapshot (the whole graph with every quoted evidence line), the run manifest, the lineage artifacts and the job record are keyed by run id only and stayed behind. Deleting a project had the same hole. | A deleted analysis still sat in the database in readable form. In a controlled environment, "delete" must mean delete. | One purge clears every table that has a `run_id` column (so a table added later is covered), and a project delete also clears everything keyed by the project. A test discovers the run-keyed tables from the schema, fills them, deletes, and requires zero rows. |
| 2 | The diff matched entities by exact lower-cased name. Two runs of the same papers shared **6 entities**; "Ciliary beat frequency (CBF)" and "Ciliary Beat Frequency", "Interleukin-8 (IL-8)" and "Interleukin-8" counted as different. Relationships were compared by those names too: **1 in common out of 25**. | The diff mostly reported spelling. | Names are matched after folding case, accents, punctuation, plurals and bracketed abbreviations ("Ciliary beat frequency (CBF)" is recognised as that, as "Ciliary Beat Frequency" and as "CBF"). A key shared by two entities of one graph is not used (ambiguous). Matched pairs with different wording are listed as renamed. Relationships are compared between matched entities. On the same pair: 8 common (from 6). |
| 3 | A snapshot kept only source, target, relation, paper and evidence. The grounded graph's page numbers, evidence ids, relationship ids and "grounded" flags were dropped. | A saved graph was less than the graph that was shown. | Every field is kept (snapshot version 2). Version 1 snapshots still load and diff. |
| 4 | The snapshot's relationship count was the number before dangling relationships were dropped, so the stored count and the stored list could disagree. | A count that does not match what is stored. | The count is of what is stored; the number skipped is returned (`skipped_relationships`). |
| 5 | The diff screen showed only counts and entity names. | Relationship differences were invisible. | It lists relationships that appear in only one run and says how many shared entities are worded differently. |

## What is still different between two runs, and why

Most of the remaining differences are real: the 8 shared entities include the central ones (cystic fibrosis, CFTR modulators,
Pseudomonas aeruginosa), and the two runs extracted different relationships between them (1 common of 25). What spelling cannot
reconcile is left as different: "FEV1" and "Forced expiratory volume in 1 s", "AAV" and "Adeno-associated viruses", "mRNA" and
"Messenger RNA". Matching those would need a glossary or a model, and a wrong merge is worse than a visible difference.

## Still open

- Cached content that is not keyed by a run (extracted wiki pages, parameters, evidence, references, literature checks) outlives a deleted run; it is keyed by the content of the paper. "Saved results" in Settings clears each cache; a deployment with a deletion requirement needs a purge that does it as part of deleting a project.
- Project folders on disk: deleting a project moves its folder aside rather than erasing it (PR-18); a deployment needs the erase step as well.
- Snapshots are compared by name only. Two runs on different papers can be diffed, and the result says little.
