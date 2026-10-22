from pathlib import Path

from tests.fixtures.make_golden_run import golden_results, legacy_results
from ui import components, theme, viewmodels as vm

ROOT = Path(__file__).resolve().parent.parent


def test_overview_counts_for_golden_and_legacy_runs():
    g = vm.overview(golden_results())
    assert [lbl for _, lbl in g] == ["Papers Analysed", "Graph Entities", "Communities", "Gaps Found", "Proposals"]
    assert [v for v, _ in g] == [3, 0, 0, 2, 1]
    assert [v for v, _ in vm.overview(legacy_results())] == [3, 0, 0, 2, 1]


def test_overview_uses_graph_stats_when_present():
    res = {"papers": [1], "graph": {"stats": {"entity_count": 9, "community_count": 2}}, "gaps": [], "proposals": []}
    assert [v for v, _ in vm.overview(res)] == [1, 9, 2, 0, 0]


def test_run_header_formats_time_and_escapes_the_name():
    meta = {"name": "p < 0.05 <b>", "created_at": "2026-10-22T13:05:59", "n_papers": 3, "n_gaps": 7}
    h = vm.run_header(meta)
    assert h["name"] == "p &lt; 0.05 &lt;b&gt;" and h["when"] == "2026-10-22 13:05"
    assert h["stats"] == " · 3 papers · 7 gaps"


def test_run_header_falls_back_when_the_run_is_unknown():
    assert vm.run_header(None, "My run") == {"name": "My run", "when": "", "stats": "", "chips": []}
    assert vm.run_header({}, "")["name"] == "Saved run"


def test_trace_rows_are_numbered_and_default_the_status():
    rows = vm.trace_rows([{"stage": "a", "inputs": "i", "outputs": "o"},
                          {"stage": "b", "inputs": "i", "outputs": "o", "status": "⚠️"}])
    assert [(r["n"], r["status"]) for r in rows] == [(1, "✅"), (2, "⚠️")]
    assert vm.trace_rows(None) == []


def test_stage_status_reports_the_worst_row():
    assert vm.stage_status([]) == "ok"
    assert vm.stage_status([{"status": "✅"}, {"status": "⚠️"}]) == "degraded"
    assert vm.stage_status([{"status": "⚠️"}, {"status": "❌"}]) == "failed"


def test_theme_has_three_stylesheets_and_nothing_else_inline():
    assert all("<style>" in c and "</style>" in c for c in (theme.CSS_BASE, theme.CSS_ENTERPRISE, theme.CSS_EXTRA))
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "--surface:" not in app and "@keyframes shimmer" not in app     # moved to ui/theme.py


def test_components_render_the_same_markup_as_before():
    assert components.badge("x").startswith('<span style="display:inline-block;padding:0.15rem 0.5rem;')
    assert "T1 " in components.tier_badge(1)
    assert components.card("T", "B").startswith('<div class="stage-card"><div class="stage-title"')
