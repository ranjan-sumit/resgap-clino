"""View-models for the Computational Lab screen: the verdict first, then the parameters per paper."""
from __future__ import annotations

_ALGORITHM_NAMES = {
    "monte_carlo": "Monte Carlo", "markov_chain": "Markov chain", "survival_analysis": "Survival analysis",
    "bayesian_network": "Conditional risk", "bootstrap": "Bootstrap", "tornado": "Tornado sensitivity",
    "hybrid": "Monte Carlo + Markov",
}


def _kind(p: dict) -> str:
    return p.get("evidence_kind") or "measured"


def lab_verdict(cr: dict) -> dict:
    """One answer to "what did the Lab actually do with these papers?" """
    params = cr.get("params") or []
    sim = cr.get("sim_results") or {}
    skipped_reason = cr.get("simulation_skipped")
    opinion = sum(1 for p in params if _kind(p) == "opinion")
    flagged = sum(1 for p in params if p.get("sanity_issues"))
    measured = sum(1 for p in params if _kind(p) != "opinion" and not p.get("sanity_issues") and not p.get("is_derived"))
    ran = list(sim.get("models_run") or [])
    refused = dict(sim.get("models_skipped") or {})
    if skipped_reason:
        state, headline = "skipped", "No simulation was run: the papers do not contain enough usable numbers."
    elif ran:
        state = "simulated"
        headline = f"Simulation run with {len(ran)} algorithm(s) on {measured} measured parameters."
    else:
        state = "skipped"
        headline = "No algorithm had the inputs it needs, so nothing was simulated."
    algorithms = [{"name": _ALGORITHM_NAMES.get(k, k), "state": "ran", "reason": ""} for k in ran]
    algorithms += [{"name": _ALGORITHM_NAMES.get(k, k), "state": "refused", "reason": why} for k, why in refused.items()]
    reasons = [skipped_reason] if skipped_reason else []
    if opinion:
        reasons.append(f"{opinion} parameter(s) are opinions (what respondents said) and are not used to simulate.")
    if flagged:
        reasons.append(f"{flagged} parameter(s) have impossible values and were set aside.")
    return {"state": state, "headline": headline, "reasons": reasons, "algorithms": algorithms,
            "measured": measured, "opinion": opinion, "flagged": flagged,
            "coverage": (cr.get("sufficiency") or {}).get("coverage_score")}


def parameters_by_paper(cr: dict, papers: list[dict]) -> list[dict]:
    """One row per paper: how many of its parameters are measured, opinion, flagged. Papers with none say so."""
    params = [p for p in cr.get("params") or [] if not p.get("is_derived")]
    rows = []
    for i, paper in enumerate(papers):
        fname = paper.get("filename", f"Paper {i + 1}")
        mine = [p for p in params if p.get("paper_index") == i or (p.get("source_file") and p.get("source_file") == fname)]
        rows.append({
            "paper": fname, "total": len(mine),
            "measured": sum(1 for p in mine if _kind(p) != "opinion" and not p.get("sanity_issues")),
            "opinion": sum(1 for p in mine if _kind(p) == "opinion"),
            "flagged": sum(1 for p in mine if p.get("sanity_issues")),
        })
    return rows


def kind_badge(p: dict) -> str:
    if p.get("sanity_issues"):
        return "impossible value"
    return "opinion" if _kind(p) == "opinion" else ""
