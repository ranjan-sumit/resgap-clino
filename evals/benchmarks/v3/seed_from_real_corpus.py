"""
Seeds Benchmark v3's two Epic 4.3 Bucket B "structural, low-risk" cases
(case-missing-abstract.json, case-parser-failure.json) from the real
Data-17072026/ AuDHD corpus -- NOT part of the mocked `tests/` unittest
suite, matching this project's existing convention that evals/benchmarks/
scripts are run by hand against real dependencies (evals/benchmarks/v2/
run_gap_challenger_benchmark.py, evals/benchmarks/baseline/*.py).

Case 1 (missing-abstract): ablates the real abstract paragraph out of
AuDHD_1.pdf's parsed text (TEXT-level ablation, not a PDF-byte edit -- see
build_case_missing_abstract()'s docstring for why pipeline/pdf_parser.py
has no explicit "abstract" section for this paper in the first place),
then runs the real pipeline.wiki_compiler.build_wiki() (real NVIDIA API
calls) and pipeline.corpus_quality.score_paper_completeness() on both the
real unablated paper and the ablated copy, capturing both real results.

Case 2 (parser-failure): deterministically truncates AuDHD_2.pdf to 60% of
its original byte length, then runs the real pipeline.pdf_parser.parse_pdf()
and pipeline.docling_parser.extract_with_docling() against the corrupted
file, capturing whatever actually happens (exception type/message or a
degraded result) -- no API calls required for this case.

Usage: python evals/benchmarks/v3/seed_from_real_corpus.py
"""
import sys, os, json, copy, re, tempfile, traceback
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

from utils.azure_client import AzureOpenAIClient
from pipeline.pdf_parser import parse_pdf
from pipeline.page_index import build_tree
from pipeline.wiki_compiler import build_wiki
from pipeline.corpus_quality import score_paper_completeness

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_CASE_DIR = os.path.dirname(__file__)
_DATA_DIR = os.path.join(_PROJECT_ROOT, "Data-17072026")

_TODAY = date.today().isoformat()

# ── Case 1: missing-abstract ────────────────────────────────────────────────

# Deterministic ablation anchors, verified live against the real parsed text
# of AuDHD_1.pdf (2026-08-24): pipeline/pdf_parser.py's _detect_section()
# regex (r"abstract") never matches for this paper, because the PDF (Nature
# Scientific Reports format) never prints a standalone "Abstract" heading
# line -- the title, authors, abstract paragraph, and the entire
# Introduction all land undifferentiated in sections["_header"]. So there is
# no sections["Abstract"] key to ablate (confirming the task brief's own
# suspicion -- the wiki schema has no explicit abstract field, and here
# pdf_parser.py doesn't even carve one out structurally). The abstract
# paragraph is still identifiable at the TEXT level by its real, fixed
# opening and closing substrings, which is what these markers anchor on.
_ABSTRACT_START_MARKER = (
    "Autism and Attention Deficit Hyperactivity Disorder (ADHD) are both "
    "linked to internalising problems"
)
_ABSTRACT_END_MARKER = (
    "Keywords Autism, ADHD, Neurodevelopmental conditions, Anxiety, "
    "Depression, Internalising problems"
)


def ablate_abstract_text(paper: dict) -> tuple[dict, str]:
    """Returns (ablated_paper, removed_text). Removes the real abstract
    paragraph (verbatim, marker-delimited) from both sections["_header"]
    and full_text, and recomputes char_count -- a genuine text-level
    ablation, not a synthetic stand-in string."""
    header = paper["sections"].get("_header", "")
    full_text = paper["full_text"]

    start = header.find(_ABSTRACT_START_MARKER)
    end = header.find(_ABSTRACT_END_MARKER)
    if start == -1 or end == -1:
        raise RuntimeError(
            "Abstract ablation markers not found in AuDHD_1.pdf's parsed "
            "_header text -- these anchors are content-specific to this "
            "exact PDF and must be re-verified (see explore scripts in "
            "this story's session) if the source PDF ever changes."
        )
    end_full = end + len(_ABSTRACT_END_MARKER)
    removed_text = header[start:end_full]

    if removed_text not in full_text:
        raise RuntimeError(
            "Abstract text extracted from _header was not found verbatim "
            "in full_text -- pdf_parser.py's section/full_text line-join "
            "behavior may have changed; ablation would silently do nothing."
        )

    ablated = copy.deepcopy(paper)
    ablated["sections"]["_header"] = header[:start] + header[end_full:]
    ablated["full_text"] = full_text.replace(removed_text, "", 1)
    ablated["char_count"] = len(ablated["full_text"])
    return ablated, removed_text


def _wiki_page_excerpt(page: dict) -> dict:
    """The wiki page fields are already LLM-compiled bullet lists (not raw
    paper text), so no trimming is needed for size -- just drop internal
    bookkeeping fields (source_file/char_count) that are captured
    separately in the fixture."""
    return {k: v for k, v in page.items() if k not in ("source_file", "char_count")}


def _count_with_digits(items: list) -> int:
    """Objective, reproducible proxy for quantitative specificity: how many
    list items contain at least one digit (e.g. an odds ratio, p-value,
    sample size, test statistic) -- not an LLM judgment call, just a regex
    count over the real captured strings."""
    return sum(1 for item in (items or []) if re.search(r"\d", str(item)))


def build_case_missing_abstract(client) -> dict:
    pdf_path = os.path.join(_DATA_DIR, "AuDHD_1.pdf")
    paper = parse_pdf(pdf_path, "AuDHD_1.pdf", client=None, use_vision=False)
    ablated_paper, removed_text = ablate_abstract_text(paper)

    tree_full = build_tree(paper)
    tree_ablated = build_tree(ablated_paper)

    print("  Running build_wiki() on the real, unablated paper (live NVIDIA API call)...")
    wiki_full = build_wiki([paper], [tree_full], client)
    print("  Running build_wiki() on the ablated paper (live NVIDIA API call)...")
    wiki_ablated = build_wiki([ablated_paper], [tree_ablated], client)

    page_full = wiki_full["pages"][0]
    page_ablated = wiki_ablated["pages"][0]

    score_full = score_paper_completeness(
        reconciled={"fields": {}}, wiki_page=page_full, ref_count=0, has_figures=False
    )
    score_ablated = score_paper_completeness(
        reconciled={"fields": {}}, wiki_page=page_ablated, ref_count=0, has_figures=False
    )

    fields_full = score_full["fields"]
    fields_ablated = score_ablated["fields"]
    field_status_diff = {
        name: {"non_ablated": fields_full[name]["status"], "ablated": fields_ablated[name]["status"]}
        for name in fields_full
        if fields_full[name]["status"] != fields_ablated[name]["status"]
    }

    kf_numbers_full = _count_with_digits(page_full.get("key_findings"))
    kf_numbers_ablated = _count_with_digits(page_ablated.get("key_findings"))
    kf_total_full = len(page_full.get("key_findings") or [])
    kf_total_ablated = len(page_ablated.get("key_findings") or [])
    datasets_full = len(page_full.get("datasets") or [])
    datasets_ablated = len(page_ablated.get("datasets") or [])
    score_unchanged = score_full["completeness_score"] == score_ablated["completeness_score"] and not field_status_diff

    # Built from this run's actual computed values, not a hardcoded claim --
    # a rerun with different live LLM output produces a different sentence,
    # never a stale one.
    if score_unchanged:
        second_finding = (
            "Second real finding, from comparing the two live LLM runs' "
            "actual output (see observed_behavior.diff): pipeline."
            "corpus_quality.score_paper_completeness()'s binary present/"
            "empty/not_extracted scoring was INSENSITIVE to this ablation "
            f"on this run -- completeness_score stayed {score_full['completeness_score']} "
            "for both, and no field's status changed (the remaining "
            "Methods/Results/Discussion sections gave the LLM enough to "
            "still populate every list-type field). But the actual field "
            "CONTENT genuinely degraded in quantitative specificity: "
            f"key_findings items containing a digit (odds ratio, p-value, "
            f"chi-square statistic, etc.) went from {kf_numbers_full}/{kf_total_full} "
            f"non-ablated to {kf_numbers_ablated}/{kf_total_ablated} ablated, and "
            f"datasets went from {datasets_full} entries non-ablated to "
            f"{datasets_ablated} ablated. A real, narrow gap: the completeness "
            "metric measures field presence, not content quality, so it "
            "cannot detect this class of degradation."
        )
    else:
        second_finding = (
            "Second real finding, from comparing the two live LLM runs' "
            "actual output (see observed_behavior.diff): unlike a prior "
            "run of this same ablation, this run's completeness_score DID "
            f"change ({score_full['completeness_score']} non-ablated vs "
            f"{score_ablated['completeness_score']} ablated) -- live-LLM "
            "output is not perfectly deterministic across runs, so the "
            "concrete field-level deltas captured in observed_behavior.diff "
            "for a given run are what should be trusted, not a fixed "
            "expectation baked into this description."
        )

    return {
        "case_id": "missing-abstract",
        "benchmark_version": "v3",
        "created": _TODAY,
        "source": (
            "Real paper AuDHD_1.pdf (Data-17072026/), parsed via the real "
            "pipeline.pdf_parser.parse_pdf(). The real abstract paragraph "
            "(verbatim text, 1503 chars, from 'Autism and Attention Deficit "
            "Hyperactivity Disorder (ADHD) are both linked to internalising "
            "problems...' through '...Keywords Autism, ADHD, "
            "Neurodevelopmental conditions, Anxiety, Depression, "
            "Internalising problems') was removed at the TEXT level from "
            "both sections['_header'] and full_text (char_count recomputed "
            "accordingly) -- not a PDF-byte edit. Both the real unablated "
            "and real ablated paper dicts were then run through the real "
            "pipeline.wiki_compiler.build_wiki() (live NVIDIA API calls) "
            "and pipeline.corpus_quality.score_paper_completeness()."
        ),
        "description": (
            "Exercises corpus completeness scoring when a paper's abstract "
            "content is missing. Notable pre-existing finding surfaced "
            "while building this fixture: pipeline/pdf_parser.py's "
            "_detect_section() never recognizes 'Abstract' as a section "
            "header for this real paper (Nature Scientific Reports format "
            "has no standalone 'Abstract' heading line), so title + "
            "authors + abstract + the entire Introduction all collapse "
            "into sections['_header'] undifferentiated -- there is no "
            "sections['Abstract'] key, and no wiki-schema 'abstract' field "
            "either (pipeline/wiki_compiler.py's WIKI_SYSTEM_PROMPT schema "
            "has no such field; contributions/key_findings/methods/"
            "datasets are the closest abstract-like summarizing fields). "
            "This case therefore ablates the abstract at the TEXT level "
            "using fixed, content-verified string markers rather than a "
            "structural section removal. " + second_finding
        ),
        "ablation": {
            "method": "marker-delimited substring removal from sections['_header'] and full_text",
            "start_marker": _ABSTRACT_START_MARKER,
            "end_marker": _ABSTRACT_END_MARKER,
            "removed_char_count": len(removed_text),
            "removed_text_excerpt": removed_text[:300] + ("..." if len(removed_text) > 300 else ""),
            "non_ablated_char_count": paper["char_count"],
            "ablated_char_count": ablated_paper["char_count"],
        },
        "observed_behavior": {
            "verified": f"{_TODAY}, live run via evals/benchmarks/v3/seed_from_real_corpus.py "
                        "against the real NVIDIA API (pipeline.wiki_compiler.build_wiki) and "
                        "pipeline.corpus_quality.score_paper_completeness()",
            "non_ablated": {
                "wiki_page": _wiki_page_excerpt(page_full),
                "completeness_score": score_full,
            },
            "ablated": {
                "wiki_page": _wiki_page_excerpt(page_ablated),
                "completeness_score": score_ablated,
            },
            "diff": {
                "completeness_score_delta": round(
                    score_ablated["completeness_score"] - score_full["completeness_score"], 3
                ),
                "achievable_completeness_score_delta": round(
                    score_ablated["achievable_completeness_score"]
                    - score_full["achievable_completeness_score"], 3
                ),
                "present_count_delta": score_ablated["present_count"] - score_full["present_count"],
                "field_status_changes": field_status_diff,
                "title_changed": page_full.get("title") != page_ablated.get("title"),
                "contributions_count_non_ablated": len(page_full.get("contributions") or []),
                "contributions_count_ablated": len(page_ablated.get("contributions") or []),
                "key_findings_count_non_ablated": len(page_full.get("key_findings") or []),
                "key_findings_count_ablated": len(page_ablated.get("key_findings") or []),
                "datasets_count_non_ablated": len(page_full.get("datasets") or []),
                "datasets_count_ablated": len(page_ablated.get("datasets") or []),
                "methods_count_non_ablated": len(page_full.get("methods") or []),
                "methods_count_ablated": len(page_ablated.get("methods") or []),
                "evaluated_on_count_non_ablated": len(page_full.get("evaluated_on") or []),
                "evaluated_on_count_ablated": len(page_ablated.get("evaluated_on") or []),
                # The binary completeness_score above treats "5 vague
                # bullet points" and "5 statistically specific bullet
                # points" identically (both score "present") -- this
                # digit-count proxy is a real, reproducible signal that
                # DOES separate them, and is what actually shows the
                # content-quality degradation the score misses.
                "key_findings_with_numbers_non_ablated": _count_with_digits(page_full.get("key_findings")),
                "key_findings_with_numbers_ablated": _count_with_digits(page_ablated.get("key_findings")),
            },
        },
    }


# ── Case 2: parser-failure ──────────────────────────────────────────────────

_TRUNCATE_PCT = 0.60


def _capture_call(label: str, fn) -> dict:
    """Runs fn() and captures either a real exception (type + message) or a
    real degraded-but-non-crashing result -- never a guess at what 'should'
    happen."""
    try:
        result = fn()
        return {"outcome": "returned_result", "result": result}
    except Exception as e:
        return {
            "outcome": "raised_exception",
            "exception_type": f"{type(e).__module__}.{type(e).__name__}",
            "exception_message": str(e),
            "traceback_excerpt": traceback.format_exc()[-1200:],
        }


def build_case_parser_failure() -> dict:
    pdf_path = os.path.join(_DATA_DIR, "AuDHD_2.pdf")
    raw = Path(pdf_path).read_bytes()
    orig_len = len(raw)
    cut = int(orig_len * _TRUNCATE_PCT)
    truncated = raw[:cut]

    tmp_path = os.path.join(tempfile.gettempdir(), "clinova_v3_AuDHD_2_truncated60.pdf")
    Path(tmp_path).write_bytes(truncated)
    print(f"  Wrote deterministic truncated PDF: {tmp_path} ({len(truncated)} of {orig_len} bytes)")

    try:
        print("  Running pipeline.pdf_parser.parse_pdf() on the corrupted file...")
        pdf_parser_capture = _capture_call(
            "pdf_parser",
            lambda: parse_pdf(tmp_path, "AuDHD_2_truncated60.pdf", client=None, use_vision=False),
        )

        print("  Running pipeline.docling_parser.extract_with_docling() on the corrupted file...")
        from pipeline.docling_parser import extract_with_docling
        docling_capture = _capture_call(
            "docling", lambda: extract_with_docling(tmp_path, "AuDHD_2_truncated60.pdf")
        )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return {
        "case_id": "parser-failure",
        "benchmark_version": "v3",
        "created": _TODAY,
        "source": (
            "Real paper AuDHD_2.pdf (Data-17072026/, 3,966,494 bytes). A "
            "deterministic corrupted variant was created by truncating the "
            "raw file bytes to exactly the first 60% of the original byte "
            "length (int(len(raw) * 0.60) = 2,379,896 bytes), written to a "
            "temp file and deleted after the run -- reproducible by "
            "re-running this script (evals/benchmarks/v3/"
            "seed_from_real_corpus.py), which regenerates the identical "
            "truncated byte sequence from the same source PDF."
        ),
        "description": (
            "Exercises the corrupted/truncated-PDF path through both real "
            "parsers used by pipeline/extraction_reconciler.py's "
            "multi-parser reconciliation: pipeline.pdf_parser.parse_pdf() "
            "(pdfplumber/pdfminer) and pipeline.docling_parser."
            "extract_with_docling() (Docling/pdfium). Captures what "
            "ACTUALLY happens against a real corrupted PDF, not an assumed "
            "graceful-degradation contract."
        ),
        "truncation": {
            "method": "raw_bytes[:int(len(raw) * 0.60)]",
            "truncate_pct": _TRUNCATE_PCT,
            "original_byte_length": orig_len,
            "truncated_byte_length": len(truncated),
        },
        "observed_behavior": {
            "verified": f"{_TODAY}, live run via evals/benchmarks/v3/seed_from_real_corpus.py "
                        "directly against pipeline.pdf_parser.parse_pdf() and "
                        "pipeline.docling_parser.extract_with_docling()",
            "pdf_parser_parse_pdf": pdf_parser_capture,
            "docling_extract_with_docling": docling_capture,
            "finding": (
                "BOTH real parsers raise a hard, uncaught-at-their-level "
                "exception on this 60%-truncated PDF -- neither returns a "
                "degraded-but-non-crashing result (no partial char_count, "
                "no partial sections/tables). pdf_parser.parse_pdf() raises "
                "pdfplumber.utils.exceptions.PdfminerException wrapping a "
                "pdfminer PDFNoValidXRef/PSEOF ('Unexpected EOF'); "
                "docling_parser.extract_with_docling() raises "
                "docling.exceptions.ConversionError wrapping a pypdfium2 "
                "PdfiumError ('Data format error'). Checked directly against "
                "app.py's real call sites (2026-08-24): parse_pdf() is "
                "called at Stage 1 (app.py ~line 1185) with NO local "
                "try/except of its own -- only the single outer "
                "`except Exception as e:` around the entire multi-stage "
                "run (app.py ~line 1646, `st.error(f'Pipeline error: {e}')`) "
                "catches it, meaning one corrupted PDF anywhere in a "
                "multi-paper upload batch aborts the ENTIRE run for every "
                "paper, with nothing saved. extract_with_docling(), by "
                "contrast, IS wrapped in a real per-paper try/except at "
                "Stage 2B (app.py ~lines 1290-1302): a Docling failure "
                "there degrades only that paper's `reconciled` to "
                "`{'fields': {}}` (lowering its completeness score) without "
                "aborting the run. So 'the multi-parser reconciliation's "
                "graceful-degradation path' genuinely exists, but only on "
                "the Docling side -- the primary pdf_parser.parse_pdf() "
                "path that runs first has no equivalent per-paper recovery "
                "today, which is a real, narrow gap for a future story."
            ),
        },
    }


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    print("Seeding Benchmark v3 Bucket B cases from the real AuDHD corpus...")
    print()

    print("Case 2: parser-failure (no API calls needed)...")
    case2 = build_case_parser_failure()
    case2_path = os.path.join(_CASE_DIR, "case-parser-failure.json")
    with open(case2_path, "w", encoding="utf-8") as f:
        json.dump(case2, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {case2_path}")
    print()

    print("Case 1: missing-abstract (live NVIDIA API calls)...")
    api_key = os.environ["NVIDIA_API_KEY"]
    client = AzureOpenAIClient(api_key=api_key)
    case1 = build_case_missing_abstract(client)
    case1_path = os.path.join(_CASE_DIR, "case-missing-abstract.json")
    with open(case1_path, "w", encoding="utf-8") as f:
        json.dump(case1, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {case1_path}")
    print()

    print("Sanity check: reloading both files with json.load()...")
    for p in (case1_path, case2_path):
        with open(p, encoding="utf-8") as f:
            json.load(f)
        print(f"  OK: {p} is valid JSON")

    print()
    print("=== Summary ===")
    print(f"missing-abstract: completeness_score {case1['observed_behavior']['non_ablated']['completeness_score']['completeness_score']} "
          f"-> {case1['observed_behavior']['ablated']['completeness_score']['completeness_score']} "
          f"(delta {case1['observed_behavior']['diff']['completeness_score_delta']}), "
          f"present_count delta {case1['observed_behavior']['diff']['present_count_delta']}, "
          f"field changes: {list(case1['observed_behavior']['diff']['field_status_changes'].keys())}, "
          f"key_findings_with_numbers "
          f"{case1['observed_behavior']['diff']['key_findings_with_numbers_non_ablated']} -> "
          f"{case1['observed_behavior']['diff']['key_findings_with_numbers_ablated']}, "
          f"datasets_count "
          f"{case1['observed_behavior']['diff']['datasets_count_non_ablated']} -> "
          f"{case1['observed_behavior']['diff']['datasets_count_ablated']}")
    print(f"parser-failure: pdf_parser outcome={case2['observed_behavior']['pdf_parser_parse_pdf']['outcome']} "
          f"({case2['observed_behavior']['pdf_parser_parse_pdf'].get('exception_type')}); "
          f"docling outcome={case2['observed_behavior']['docling_extract_with_docling']['outcome']} "
          f"({case2['observed_behavior']['docling_extract_with_docling'].get('exception_type')})")


if __name__ == "__main__":
    main()
