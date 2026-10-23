# Audit 22g: lineage and the project zip

**Input:** the real "Run 3 (agentic rerun)" and the real cystic-fibrosis project (3 PDFs, 4 runs, 21 files in the zip, 11 MB). Dated 2026-10-23.

## What was right

- The technical lineage of the real run was complete: corpus, three papers, evidence, graph, gaps, proposals, no orphans; the scientific lineage
  traced 8 gaps with no unresolved evidence ids, and 3 of them with a proposal.
- The project zip contained no API key and no local path, and every file the database lists was in it.

## Findings and fixes

| # | Finding | Effect | Fix |
|---|---|---|---|
| 1 | **The lineage "content hashes" did not hash the content.** A paper's hash was its file name and character count; the corpus's was the file names; the graph's was its entity ids (no relationships); the gap set's was the gap ids (no text or status); the proposals' was their titles; the reference set's was a count. A different PDF with the same name and length, an edited gap or a changed relationship produced the same hash. | The provenance record could not show that anything had changed. | The hashes cover the real content: the SHA-256 of each PDF's bytes, the full graph, the full gap and proposal lists, the evidence, the references (lineage schema 2). |
| 2 | There was no way to check a run against its lineage. | A recorded hash nobody can compare is decoration. | `verify_lineage(run_id)` recomputes the hashes from what is saved now and from the stored PDFs, and reports mismatches. The lineage view shows the result. A run recorded before this change is reported as "cannot be checked", never as fine (the real run above). |
| 3 | The project zip had no integrity information, and was kept whole in the browser session after "Prepare". | A copy could not be verified later; hundreds of megabytes per open session. | The zip carries `CHECKSUMS.sha256` (`sha256sum -c` format) and `verify_project_zip` finds a changed, missing or unlisted file. The export records when it was made. The download is built when requested, not stored in the session. |
| 4 | The zip followed links inside the project folder. | A link planted in the folder would copy any file from the machine into an export. | Only real files are added. (The test that creates a link was skipped here: this Windows account cannot create one.) |
| 5 | Reading one run's lineage loaded every run's artifacts and the whole run with its section text. | Slow on a large database. | Artifacts are listed for one run; the run is read without its sections. |

## Still open

- The hashes make tampering with the saved results detectable, not impossible: the hashes live in the same database. Evidence that holds
  against someone with write access needs the checksums (or the zip) stored somewhere else, signed or in append-only storage.
- Lineage of the models used is the model name in the manifest; model weights and provider versions are not hashable from outside.
- The Lab zip (`pipeline/doc_generator.build_zip`) stamps local time and has no checksums.
