"""
Research Council screen (Clinova Phase 5, Epic 5.3). Reads the real
comp_results blob load_run() returns alongside `results` for a Computational
Lab run (utils/database.py::save_run()'s comp_results parameter) --
pipeline/llm_council.py's real council_select_model()/
council_synthesise_insights() output, never invented. Only the specific run
that actually ran the Computational Lab carries this data (has_comp=1), which
may not be the project's single newest run -- scans newest-first for the
first one that does, rather than reusing dashboard_service's basis_run.
"""
from apps.api.models.common import CountStat, RunRef
from apps.api.models.council import (
    CouncilAgentResponse, ModelSelectionView, NovelFindingView, ResearchCouncilView,
)
from apps.api.services.project_runs import list_project_runs
from utils.database import load_run


def get_project_council(project_id: str) -> ResearchCouncilView:
    runs = list_project_runs(project_id)
    if not runs:
        return ResearchCouncilView(
            run=None, basis_note="No runs exist for this project yet.", params_summary=[],
            model_selection=None, novel_finding=None, clinical_insights=[], research_insights=[],
            key_uncertainties=[], actionable_next_steps=[], limitations=[], overall_confidence=None,
            insight_agents=[], sim_headline_numbers={},
            empty_reason="No runs in this project yet. Runs created in the Streamlit "
                          "workspace appear here automatically.",
        )

    comp_row = None
    comp = None
    for row in runs:
        if not row.get("has_comp"):
            continue
        loaded = load_run(row["id"]) or {}
        if loaded.get("comp_results"):
            comp_row, comp = row, loaded["comp_results"]
            break

    if comp is None:
        return ResearchCouncilView(
            run=None, basis_note="No Computational Lab run exists for this project yet.",
            params_summary=[], model_selection=None, novel_finding=None, clinical_insights=[],
            research_insights=[], key_uncertainties=[], actionable_next_steps=[], limitations=[],
            overall_confidence=None, insight_agents=[], sim_headline_numbers={},
            empty_reason="No run in this project has used the Computational Lab (Research Council) "
                          "feature yet -- it runs from the Streamlit sidebar, not this API.",
        )

    run = RunRef(run_id=comp_row["id"], name=comp_row["name"], created_at=str(comp_row["created_at"]))
    basis_note = f"Reflects the most recent Computational Lab run, \"{comp_row['name']}\" ({comp_row['id'][:8]})."

    params_summary = [
        CountStat(key="params", label="Parameters", value=len(comp.get("params") or []),
                   display=f"{len(comp.get('params') or []):,}", recorded=True, source="comp_results.params"),
        CountStat(key="t1", label="Tier 1 (Direct)", value=comp.get("t1_count", 0),
                   display=f"{comp.get('t1_count', 0):,}", recorded=True, source="comp_results.t1_count"),
        CountStat(key="t2", label="Tier 2 (Derived Input)", value=comp.get("t2_count", 0),
                   display=f"{comp.get('t2_count', 0):,}", recorded=True, source="comp_results.t2_count"),
        CountStat(key="derived", label="Derived Parameters", value=comp.get("derived_count", 0),
                   display=f"{comp.get('derived_count', 0):,}", recorded=True, source="comp_results.derived_count"),
        CountStat(key="n_runs", label="Simulation Runs", value=comp.get("n_runs", 0),
                   display=f"{comp.get('n_runs', 0):,}", recorded=True, source="comp_results.n_runs"),
    ]

    model_council = comp.get("model_council") or {}
    mc_decision = model_council.get("final_decision") or {}
    model_selection = ModelSelectionView(
        selected_model=mc_decision.get("selected_model"), rationale=mc_decision.get("rationale"),
        confidence=mc_decision.get("confidence"),
    ) if mc_decision else None

    insight_council = comp.get("insight_council") or {}
    final = insight_council.get("final_decision") or {}
    nf = final.get("novel_finding") or {}
    novel_finding = NovelFindingView(
        title=nf.get("title", ""), claim=nf.get("claim", ""),
        what_makes_it_new=nf.get("what_makes_it_new", ""), evidence_chain=nf.get("evidence_chain") or [],
        mechanism=nf.get("mechanism", ""), validation_study=nf.get("validation_study", ""),
        clinical_opportunity=nf.get("clinical_opportunity", ""),
        commercial_opportunity=nf.get("commercial_opportunity", ""),
        confidence=nf.get("confidence", "medium"), confidence_reasoning=nf.get("confidence_reasoning", ""),
    ) if nf else None

    insight_agents = [
        CouncilAgentResponse(agent=a.get("agent", ""), role=a.get("role", ""),
                               model=a.get("model", ""), response=a.get("response", ""))
        for a in insight_council.get("agents") or []
    ]

    sim = comp.get("sim_results") or {}
    headline = sim.get("headline_numbers") or {}

    return ResearchCouncilView(
        run=run, basis_note=basis_note, params_summary=params_summary, model_selection=model_selection,
        novel_finding=novel_finding, clinical_insights=final.get("clinical_insights") or [],
        research_insights=final.get("research_insights") or [],
        key_uncertainties=final.get("key_uncertainties") or [],
        actionable_next_steps=final.get("actionable_next_steps") or [],
        limitations=final.get("limitations") or [],
        overall_confidence=final.get("overall_confidence"),
        insight_agents=insight_agents, sim_headline_numbers=headline,
    )
