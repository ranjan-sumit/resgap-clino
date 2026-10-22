# PyMuPDF licence decision (B31)

**Status: open. It needs a decision from the project owner before the app is hosted for other people.**

## The problem

The app reads PDFs with PyMuPDF (`fitz`). PyMuPDF is released under the **GNU AGPL-3.0**, or under a paid
commercial licence from Artifex.

| How the app is used | AGPL consequence |
|---|---|
| Run privately by one person or one lab, not shared | None in practice. |
| Hosted as a service others can reach over a network (Streamlit Cloud with other users) | AGPL section 13: the full source of the app, including your changes, must be offered to those users. |
| Given to others as a download or Docker image | The whole app must then be offered under the AGPL as well. |

This is a summary, not legal advice.

## Options

1. **Keep PyMuPDF; the app stays private.** No cost, no code change. Do not share the hosted link with outside users.
2. **Keep PyMuPDF and publish the app source under the AGPL.** No cost. Possible if the project is meant to be open source.
3. **Buy the Artifex commercial licence.** Removes the obligation; the cost is a quote from Artifex.
4. **Switch to a permissively licensed parser** (pypdfium2, BSD/Apache; pdfminer.six, MIT; pdfplumber, MIT, already a dependency).
   The cost is engineering: page text blocks with positions and fonts feed the structural parser, furniture stripping, table
   segments and the evidence reader's page-tagged quotes. Parser contract tests on the fixture PDFs would have to pass before switching.

## Where PyMuPDF is used

`pipeline/pdf_parser.py` (readability check, text, vision page images), `pipeline/docling_parser.py` (structural parser: blocks, fonts,
tables, furniture), `app.py` (character count for the cost estimate), `pipeline/pdf_limits.py` users via `check_pdf_readable`.
pdfplumber is the existing fallback when `fitz` is missing, so text extraction would still work, with less structure.

## Recommendation

Choose option 1 now (private use) and revisit before PR-23 (cloud readiness), because sharing a hosted link is the moment
the obligation starts. If the app is going to be shared, decide between options 2 and 3 first; option 4 is only worth its cost
if neither is acceptable.
