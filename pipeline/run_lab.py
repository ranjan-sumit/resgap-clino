"""
Computational Lab (Stages 8-12) as one callable, with a data-sufficiency gate.

The Lab used to be written inline in app.py, so it could not be tested or run from a script, and it
had no gate: in a real run the sufficiency check scored the extracted parameters 1/10 and said
"insufficient", yet the Lab still simulated and reported "5-year survival = 6.76%" and a "posterior
probability" built from a survey RESPONSE RATE. Numbers like that are worse than no numbers.

Now, when the papers do not contain enough usable quantitative parameters, the simulation and the
model-selection council are skipped (recorded with the reason), and the insight council is told
plainly that no simulation was run so it reasons from the hypotheses and gaps only.
"""
from typing import Callable

from pipeline.discovery_engine import run_discovery_engine
from pipeline.doc_generator import build_zip
from pipeline.grounding import annotate_claims, corpus_numbers, corpus_words
from pipeline.llm_council import council_select_model
from pipeline.multi_run import run_multi_council
from pipeline.paper_manager import extract_tier2_parameters
from pipeline.param_extractor import (
    check_sufficiency, derive_cross_paper_parameters, extract_parameters, params_to_csv,
)
from pipeline.param_quality import annotate_parameters, is_modelling_input
from pipeline.simulation_engine import filter_confident_params, run_simulation, runnable_models

MIN_COVERAGE_TO_SIMULATE = 4        # sufficiency coverage_score (0-10) below this: do not simulate
MIN_USABLE_PARAMS = 3               # numeric, directly extracted, not low-confidence


def _noop(*_a, **_k) -> None:
    return None


def usable_parameters(params: list) -> list:
    """Parameters a simulation can legitimately start from: a number, read from a paper (not
    derived from other parameters), and not flagged low-confidence."""
    return [p for p in params
            if not p.get("is_derived") and p.get("confidence") != "low" and is_modelling_input(p)
            and isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool)]


def simulation_gate(params: list, sufficiency: dict) -> tuple[bool, str]:
    """(allowed, reason_if_not)."""
    sufficiency = sufficiency or {}
    usable = usable_parameters(params)
    coverage = sufficiency.get("coverage_score")
    if sufficiency.get("recommendation") == "insufficient":
        return False, (f"the sufficiency check judged the extracted parameters insufficient for modelling"
                       f" (coverage {coverage}/10)"
                       + (f"; missing: {', '.join(str(m) for m in sufficiency['missing_critical'][:4])}"
                          if sufficiency.get("missing_critical") else ""))
    if isinstance(coverage, (int, float)) and coverage < MIN_COVERAGE_TO_SIMULATE:
        return False, f"parameter coverage is {coverage}/10 (needs at least {MIN_COVERAGE_TO_SIMULATE})"
    if len(usable) < MIN_USABLE_PARAMS:
        return False, (f"only {len(usable)} usable numeric parameters were found "
                       f"(needs at least {MIN_USABLE_PARAMS})")
    return True, ""


def council_problem(council: dict) -> str | None:
    """Why the insight council produced nothing, or None if it produced findings. A real run
    ended "complete" with an empty council because the chair's model was out of quota, and
    nothing said so."""
    fd = council.get("final_decision") or {}
    if any(fd.get(k) for k in ("novel_finding", "clinical_insights", "research_insights", "actionable_next_steps")):
        return None
    runs = [r for r in council.get("all_runs", []) if isinstance(r, dict)]
    errs = [(r.get("final_decision") or {}).get("chair_error") for r in runs]
    errs = [e for e in errs if e]
    failed = sum(1 for a in council.get("all_agents", []) if a.get("failed") or a.get("_failed"))
    return ("the insight council produced no findings: the chair did not answer"
            + (f" ({str(errs[0])[:160]})" if errs else "")
            + (f"; {failed} council agent call(s) failed" if failed else ""))


def skipped_simulation(reason: str) -> dict:
    return {"skipped": True, "skip_reason": reason, "model_used": "none (simulation skipped)",
            "models_run": [], "scenarios_run": [], "algorithm_results": {}, "headline_numbers": {},
            "sensitivity_ranking": [], "scenario_results": {}, "summary": {"models_run": [], "total_results": 0},
            "excluded_low_confidence": []}


def skipped_model_council(reason: str) -> dict:
    return {"skipped": True, "agents": [], "consensus": {}, "transcript": "",
            "final_decision": {"selected_model": "none (simulation skipped)", "rationale": reason, "scenarios": [],
                               "key_parameters_to_use": [], "parameters_to_flag": [], "confidence": "n/a"}}


def run_computational_lab(results: dict, context: dict, client, domain_config: dict | None = None,
                          n_council_runs: int = 2, progress: Callable[[str, int], None] = _noop,
                          trace: Callable[[str, str, str], None] = _noop) -> dict:
    """Runs Stages 8A-12 on a finished run's `results` and returns the comp_results dict
    (the same shape the app stores). Raises only if a stage itself raises; a skipped simulation
    is a normal outcome recorded in comp_results["simulation_skipped"]."""
    wiki = results.get("wiki", {})
    gaps = results.get("gaps", [])
    ref_papers = results.get("ref_papers", [])

    client.set_stage("Lab — Parameter extraction")
    papers_raw = [{"sections": p.get("sections", {}), "tables": p.get("tables", []), "filename": p.get("filename", "")}
                  for p in results.get("papers", [])]
    progress("Stage 8A — Extracting Tier 1 parameters…", 8)
    study_types = {}
    for fn, prof in (results.get("paper_profiles") or {}).items():
        study_types[fn] = (prof or {}).get("study_type")
    for pg in wiki.get("pages", []):
        if pg.get("source_file") in study_types and pg.get("title"):
            study_types[pg["title"]] = study_types[pg["source_file"]]
    t1_params = extract_parameters(wiki, papers_raw, client, study_types)

    t2_params = []
    tier2_refs = [r for r in ref_papers if r.get("tier") == 2 and r.get("abstract")]
    if tier2_refs:
        progress(f"Stage 8A-T2 — Extracting Tier 2 params from {len(tier2_refs)} ref abstracts…", 14)
        t2_params = extract_tier2_parameters(tier2_refs, client)

    params = t1_params + t2_params
    annotate_parameters(params, study_types)
    modelling = [p for p in params if is_modelling_input(p)]       # opinions and impossible values never count
    progress("Stage 8A — Deriving cross-paper values…", 18)
    derived = derive_cross_paper_parameters(modelling, client)
    for d in derived:
        d.setdefault("evidence_kind", "measured")
    params += derived
    modelling += derived
    sufficiency = check_sufficiency(modelling, client)
    sufficiency["opinion_excluded"] = sum(1 for p in params if p.get("evidence_kind") == "opinion")
    sufficiency["impossible_excluded"] = sum(1 for p in params if p.get("sanity_issues"))
    sufficiency["parameter_count"] = len(modelling)
    csv_data = params_to_csv(params)
    trace("Stage 8A — Parameters", f"{len(papers_raw)} T1 papers + {len(tier2_refs)} T2 abstracts",
          f"{len(t1_params)} T1 + {len(t2_params)} T2 + {len(derived)} derived = {len(params)} total")

    progress("Stage 8B — Cross-paper discovery engine…", 27)
    client.set_stage("Lab — Discovery")
    discovery = run_discovery_engine(wiki, params, context, client, domain_config)
    trace("Stage 8B — Discovery", f"{len(wiki.get('pages', []))} wiki pages",
          f"{len(discovery.get('hypotheses', []))} novel hypotheses")

    allowed, reason = simulation_gate(params, sufficiency)
    if allowed:
        progress(f"Stage 9 — LLM Council selecting model ({len(params)} params)…", 42)
        model_council = council_select_model(params, sufficiency, context, client)
        simulation_params, _ = filter_confident_params(params)
        models_auto = runnable_models(simulation_params, model_council, sufficiency)
        progress(f"Stage 10 — Running {len(models_auto)} algorithms: {', '.join(models_auto)}…", 57)
        sim_results = run_simulation(params, model_council, sufficiency)
        trace("Stage 10 — Simulation", f"{len(models_auto)} algorithms selected",
              f"Models: {sim_results.get('models_run', [])} run")
    else:
        model_council, sim_results = skipped_model_council(reason), skipped_simulation(reason)
        progress("Stage 10 — Simulation skipped (not enough quantitative data)…", 57)
        trace("Stage 10 — Simulation", "usable parameters: " + str(len(usable_parameters(params))),
              f"SKIPPED: {reason}. Insights below are qualitative and make no numerical prediction.")

    def _cp(run_num, total):
        progress(f"Stage 11 — Council run {run_num}/{total}…", 74 + int((run_num - 1) / total * 12))
    progress(f"Stage 11 — Council synthesising insights ({n_council_runs}× runs)…", 74)
    merged_council = run_multi_council(n_runs=n_council_runs, sim_results=sim_results, discovery=discovery,
                                       params=params, gaps=gaps, context=context, client=client,
                                       progress_callback=_cp)

    council_error = council_problem(merged_council)
    if council_error:
        trace("Stage 11 — Insight council", f"{n_council_runs} runs", f"WARNING: {council_error}")

    # Flag effect sizes in the new finding that no paper (or simulation) actually reports.
    known = corpus_numbers(wiki, params, discovery, results.get("evidence_objects"), sim_results.get("headline_numbers"))
    novel = [(merged_council.get("final_decision") or {}).get("novel_finding")]
    novel += [g.get("best") for g in merged_council.get("novel_finding_groups", []) if isinstance(g, dict)]
    paper_text = [p.get("sections") for p in results.get("papers", [])]
    annotate_claims([n for n in novel if isinstance(n, dict)], ("title", "claim"), known,
                    known_words=corpus_words(wiki, params, results.get("evidence_objects"), paper_text))

    progress("Stage 12 — Building report package…", 90)
    zip_bytes = build_zip(params_csv=csv_data, sim_results=sim_results, model_council=model_council,
                          insight_council=merged_council, context=context, params=params,
                          sufficiency=sufficiency, discovery=discovery)
    progress("Lab complete", 100)
    return {
        "params": params, "derived_count": len(derived),
        "t1_count": len(t1_params), "t2_count": len(t2_params),
        "sufficiency": sufficiency, "csv_data": csv_data,
        "discovery": discovery, "model_council": model_council,
        "sim_results": sim_results, "insight_council": merged_council,
        "n_runs": n_council_runs, "zip_bytes": zip_bytes,
        "simulation_skipped": None if allowed else reason,
        "council_error": council_error,
    }
