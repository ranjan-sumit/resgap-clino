"""Text from papers, models and users must never reach the page as markup.

Every f-string that builds HTML (its fixed text contains a tag) may only interpolate:
  * a value passed through esc() / html.escape(),
  * a number-producing call (len, int, round ...),
  * HTML built elsewhere by a helper that escapes its own inputs (the badge helpers), or
  * an expression listed in SAFE below after review (colours, constants, numbers, pre-escaped variables).
A new unescaped value fails this test until it is escaped or reviewed.
"""
import ast
import re
from pathlib import Path

import pytest

from ui.components import esc

ROOT = Path(__file__).resolve().parent.parent
FILES = ["app.py", "utils/export.py"] + sorted(f"ui/{p.name}" for p in (ROOT / "ui").glob("*.py"))

ESCAPERS = {"esc", "_esc", "escape"}
NUMBERS = {"len", "int", "float", "round", "sum", "max", "min", "abs"}
HTML_BUILDERS = {"_badge", "badge", "_tier_badge", "tier_badge", "_bullets", "_reference_cell", "_doi_cell",
                 "_evidence_rows", "_lab_html", "kind_badge", "_rows_html", "_state_box"}

# Reviewed: each is a colour, a number, a constant, or a variable that was escaped where it was built.
SAFE = {
    "color", "cc", "sc", "_vc", "conf_c", "icon", "bar", "extra", "chips", "_chips", "status", "json_note",
    "t_class", "prefix", "title_text", "authors", "venue", "abstract", "source", "quote", "cited", "ci", "derived_t",
    "label_extra", "_MARK", "_points_html", "_flow_html", "freq", "i", "t1c", "t2c", "score", "tier2_count",
    "abstract_count", "n_council_runs",
    "r['latency_s']", "g['papers']", "g['rank'] or '–'", "res_cfg['icon']", "g['frequency']",
    "cov.get('total_clinical_insights', 0)", "cov.get('total_next_steps', 0)", "cov.get('total_novel_findings', 0)",
    "cr.get('derived_count', 0)", "_cur_project_stats.get('paper_count', 0)",
    "'Simulated' if _v['state'] == 'simulated' else 'Not simulated'",
    "'✓ A key is set.' if _has_key else 'Open Settings and paste an API key.'",
    "' or use the papers already in this project' if _cur_project_stats.get('paper_count') else ''",
    "'#' + str(r['rank']) + ' ' if r['rank'] else ''",
    "' · ' + html.escape(where) if where else ''",
    "html.escape(str(doi)[:40]) if doi else 'no DOI'", "source or 'parsed'",
    "_badge(label, color, bg, border, title=_def)", "_badge(*ch, title=glossary_lookup(ch[0])) if ch else ''",
    "_badge(freq, '#4a6580', '#f2f5f8', '#c9dff5')", "_badge(g['frequency'], '#4a6580', '#f2f5f8', '#c9dff5')",
}


SAFE_IN = {   # reviewed per file: HTML pieces built from other linted f-strings, numbers and constants
    # _rm_name and chip_html come from ui/viewmodels.run_header, which escapes them (tested in test_ui_viewmodels)
    "app.py": {"_CHECK", "_rm_name", "chip_html", "gq['quality_score']", "gq['extraction_coverage']", "gq['evidence_coverage']",
               "gq['duplicate_rate']", "gq['unresolved_entity_rate']",
               # Reviewed 2026-10-23 (Run planner, graph screen, run bar, tables). Each is HTML assembled from esc()'d
               # pieces, a number, or a constant (class names, colours, column titles), never raw paper or model text:
               "_HERO_ART",                                                    # constant SVG
               "_last_run", "_meta", "_status_cls", "_status",                 # project header and run bar (esc'd; chips come from run_header)
               "rows_html", "_rows", "_cov_rows", "_gap", "_i", "_title", "c",   # table bodies and headings built from esc()'d cells
               "badges", "money", "sub", "saving", "main_rows", "council_rows", "includes",   # the planner card's parts
               "_model(r)",                                                    # returns esc(model name)
               "_RP_COLORS[r]", "(cost['by_role'].get(r) or 0) / mid * 100",   # slate colours; a percentage
               "_label_color.get(r['type'], '#8fa6bd')", "r['connections']"},  # type colour from the palette; a count
    "utils/export.py": {"title", "param_rows", "hyp", "headline", "drivers", "now", "paper_rows", "ref_rows", "gap_cards", "proposal_cards",
                        "entity_rows", "rel_rows", "trace_rows", "evidence_rows", "evidence_count",
                        "graph_stats.get('entity_count', 0)", "graph_stats.get('relationship_count', 0)",
                        "graph_stats.get('community_count', 0)", "_status_class(g.get('validation_status'))",
                        "block('Parameters still missing', s['missing'])", "block('Clinical insights', s['clinical'])",
                        "block('Research insights', s['research'])", "block('Suggested next steps', s['next_steps'])",
                        "block('Limitations of the Lab analysis', s['limitations'])"},
    # the badge/card/label helpers take HTML by design; their callers are what this test checks
    "ui/components.py": {"text", "title", "t", "role", "hint_html", "hint", "bg", "border", "body", "w"},
}


def _name(func) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _is_safe(node, extra=frozenset()) -> bool:
    if ast.unparse(node) in SAFE or ast.unparse(node) in extra:
        return True
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.JoinedStr):
        return True                                   # its own interpolations are checked on their own
    if isinstance(node, ast.Call):
        name = _name(node.func)
        if name in ESCAPERS or name in NUMBERS or name in HTML_BUILDERS:
            return True
        if name == "join":                            # "".join(<generator of f-strings>)
            return True
    if isinstance(node, ast.IfExp):
        return _is_safe(node.body, extra) and _is_safe(node.orelse, extra)
    if isinstance(node, ast.BinOp):
        return _is_safe(node.left, extra) and _is_safe(node.right, extra)
    return False


def _builds_html(js: ast.JoinedStr) -> bool:
    text = "".join(v.value for v in js.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return bool(re.search(r"<[A-Za-z/]", text))


def unescaped_interpolations(source: str, extra=frozenset()) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr) and _builds_html(node):
            for part in node.values:
                if isinstance(part, ast.FormattedValue) and not _is_safe(part.value, extra):
                    found.append((node.lineno, ast.unparse(part.value)))
    return found


@pytest.mark.parametrize("rel", FILES)
def test_html_strings_only_interpolate_escaped_or_reviewed_values(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert unescaped_interpolations(source, SAFE_IN.get(rel, frozenset())) == []


def test_the_lint_finds_a_raw_value_and_accepts_an_escaped_one():
    assert unescaped_interpolations("x = f'<b>{title}</b>'") == [(1, "title")]
    assert unescaped_interpolations("x = f'<b>{paper[\"title\"]}</b>'") != []
    assert unescaped_interpolations("x = f'<b>{esc(title)}</b>'") == []
    assert unescaped_interpolations("x = f'<b>{html.escape(title)}</b>'") == []
    assert unescaped_interpolations("x = f'no markup {title}'") == []


# ── behaviour: a hostile value is shown as text ────────────────────────────────────────────────────
HOSTILE = '<img src=x onerror=alert(1)><script>alert(2)</script>"\''


def test_esc_neutralises_markup_quotes_and_none():
    out = esc(HOSTILE)
    assert "<" not in out and ">" not in out and '"' not in out and "'" not in out
    assert esc(None) == "" and esc(5) == "5"


def test_a_hostile_title_is_rendered_as_text_on_every_result_screen(app_test, isolated_env):
    import copy
    from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
    res = copy.deepcopy(golden_results())
    for g in res["gaps"]:
        g["title"] = HOSTILE
    for p in res["proposals"]:
        p["title"] = HOSTILE
    for ev in (res.get("evidence") or {}).values():
        for e in ev:
            e["text"] = HOSTILE
    for page in (res.get("wiki") or {}).get("pages", []):
        page["title"] = HOSTILE
        page["contributions"] = [HOSTILE]
    seed_run(res, name=HOSTILE, comp_results=golden_comp())
    at = app_test(timeout=120)
    for section in ["Overview", "Evidence", "Wiki", "References", "Graph", "Gaps", "Proposals", "Lab", "Trace", "Export"]:
        at.session_state["result_tab"] = section
        at.run()
        assert not at.exception, section
        shown = " ".join(m.value for m in at.markdown).lower()
        # escaped text may still contain the words; what must never appear is live markup or a doubled escape
        assert "<script" not in shown and "<img" not in shown, section
        assert "&amp;lt;" not in shown and "&amp;gt;" not in shown, f"{section}: escaped twice"
        if section in ("Gaps", "Evidence", "Wiki"):
            assert "&lt;img" in shown, f"{section}: the hostile text did not reach the page as text"
