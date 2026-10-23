# Audit 22d: figure analysis (vision)

**Input:** the three cystic-fibrosis review papers (5, 5 and 7 figures), real Gemini (`gemini-3.5-flash-lite`) vision calls, 2026-10-23.

## Findings and fixes

| # | Finding (measured) | Effect | Fix |
|---|---|---|---|
| 1 | **Pages were chosen by word count** (under 80 words, or a figure word and under 200). It picked **no page at all for two of the three papers** (their figure pages carry more than 200 words) and for the third picked pages 4 and 6, which have no figure, and missed three that do. | Figure analysis "on" did nothing, or analysed the wrong pages, with no sign of it. | Figures are found from the PDF: a caption line ("Figure 3.", "Fig. 3:") with a picture or a chart drawn as vectors beside it. Logos and icons are ignored; a sentence that starts "Figure 2 shows ..." is not a caption. Found: 5, 5 and 7, matching the papers. This needs no model, so the figure list is always recorded. |
| 2 | The whole page was rendered and sent. My first test picked page 1 and the model described the publisher logo. | Cost, and descriptions of layout instead of the figure. | Only the figure's region, with its caption, is rendered (about 8 s and 1,700 tokens per figure). |
| 3 | The prompt had no caption and no limits; answers came back with markdown and LaTeX (`$7\ \mu\text{m}$`). | Hard to read; free to go beyond the figure. | The prompt names the figure's caption, asks for what is visible only, "about" for anything estimated from a bar or point, plain text, 120 words. The answer is cleaned to plain text. |
| 4 | Numbers in a description were not checked. On the survey paper the model read 17 percentages off the bar labels; on the airway-chip paper it estimated values from plot positions ("about 39%"). None are in the paper's text. | A reading of a chart could enter the wiki and the parameters looking like a quotation. | Each description lists the numbers that appear in neither the caption nor the page text, and the excerpt given to the wiki marks them `*` with the note "read from the image; not stated in the text". The excerpt is headed "described by a model from the images". |
| 5 | A failed call's error text was stored as the figure's "description" (`[Vision analysis failed: ...]`), which then went into the page index. | Error text treated as content. | Failure is an `error` field; the description stays empty and is never used. |
| 6 | The router's image path skipped what every other model call gets: the data-not-instructions rule, the rate limiter, and the run's token budget. | Image calls were free in the budget and could exceed it. | All three apply now; an image is counted at 1,200 tokens. Four figures used about 6,700 tokens in the audit. |

## Still open

- A description is the model's reading of the picture. It is labelled, not verified. Values in tables drawn as images are not read as tables.
- A figure with several panels gets one description of at most 120 words, so detail is lost.
- Figure results are not cached: the same paper analysed again pays again.
- A caption placed far from its picture (more than about 380 points) is missed; so is a figure with no caption.
- Only the first eight figures per paper are described; the rest are listed.
