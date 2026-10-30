# Manual release checklist (R-22)

A person does these on a real run before a release. Record the date, who, the commit, and anything odd. Use real papers (not the test fixtures)
and a real model key.

## Setup
- [ ] Fresh clone or fresh Docker volume; `pip install -r requirements.txt` (or `docker compose up -d --build`) works from the README alone.
- [ ] The app starts with only `.env` keys; no key is shown anywhere on screen, in the trace, or in `data/`.

## New project and analysis (as a new user)
- [ ] Create a project with a domain and a research interest.
- [ ] Upload 3 real PDFs. A 1-paper upload is refused with a clear message; a non-PDF is refused.
- [ ] Start the run. Progress moves; the token meter moves; the page can be refreshed mid-run without losing the run.
- [ ] The run finishes. Nothing says "failed" without saying why; warnings are readable.

## Read one full report end to end
- [ ] Overview: the headline and counts match the other tabs.
- [ ] Evidence: pick five items; each quote is really in the PDF on the stated page.
- [ ] Wiki: each paper has a page; cross-links open.
- [ ] References: unresolved references are labelled as such; links open the right paper.
- [ ] Graph: opens, filters work, nothing overlaps at laptop width, the labels are readable.
- [ ] Gaps: each gap names its supporting evidence; the literature verdict names a closest paper when partial or solved.
- [ ] Proposals: each links to its gap and is specific enough to act on.
- [ ] Lab (if used): a parameter that the papers do not contain is not invented.
- [ ] Trace: shows which model answered each stage.
- [ ] Export: HTML, PDF, Markdown, JSON and the project zip all open; the zip verifies.

## Project and data handling
- [ ] Rename, archive, restore, and delete a run; the Settings, Audit log tab shows each action with the right name and time.
- [ ] The audit log shows "Intact".
- [ ] Create a backup, restore it into an empty folder (`python scripts/backup.py restore <file>`), and open a run from it.
- [ ] With `RESGAP_ERASE_ON_DELETE=1`, a deleted project's folder is gone from disk.

## Controlled environment (if this release is for one)
- [ ] `RESGAP_EGRESS=none` with a custom endpoint on the allowed list: a run completes and nothing else is contacted (check with a firewall or packet log).
- [ ] The page loads with no request to any other site (browser network tab).
- [ ] Docker: the container is non-root and read-only; the port answers on the loopback address only; the reverse proxy adds TLS and sign-in.

## Accessibility and layout
- [ ] Keyboard only: reach every tab and button; focus is visible.
- [ ] Phone width (390 px), tablet (768 px) and laptop (1280 px): no horizontal scroll, nothing cut off.
