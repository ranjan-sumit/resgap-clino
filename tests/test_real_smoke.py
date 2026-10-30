"""R-21: one real run on two tiny PDFs against a real model. Spends tokens, so it only runs on request:

    python -m pytest tests/test_real_smoke.py -m real -o addopts="" -s

It needs GEMINI_API_KEY (environment or .env). The run is capped at TOKEN_CAP estimated tokens and uses the Gemini free-tier pace,
so expect several minutes. It checks that every stage completes, that evidence is quoted and paged, that nothing was rate limited
for good, and that the run stayed under its cap.
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real

ROOT = Path(__file__).resolve().parent.parent
TOKEN_CAP = 250_000

PAPERS = {
    "inhaled_steroid_trial.pdf": (
        "Inhaled budesonide in children with mild persistent asthma: a randomised trial",
        ["Abstract", "Background: Children with mild persistent asthma are often given daily inhaled corticosteroids, but the effect on growth "
         "and on exacerbations in the first year is uncertain. We randomised 240 children aged 6 to 11 years to budesonide 200 micrograms "
         "twice daily or placebo for 52 weeks.",
         "Introduction", "Asthma is the most common chronic disease of childhood. Guidelines recommend a low daily dose of an inhaled "
         "corticosteroid for children whose symptoms occur more than twice a week, because trials in adults show fewer exacerbations. "
         "Children are not small adults, however: their airways, their drug handling and their growth all differ. Earlier paediatric trials "
         "were short, often under 12 weeks, and reported symptoms rather than exacerbations. Reports of a small, early reduction in growth "
         "velocity have not been settled, and families ask whether the benefit justifies a daily medicine for a year or more.",
         "Methods", "Participants were recruited from four paediatric clinics. The primary outcome was the number of exacerbations needing "
         "oral steroids. Growth velocity was measured every 13 weeks by stadiometer. Adherence was checked by dose counters.",
         "Results", "Exacerbations needing oral steroids occurred in 18 of 120 children on budesonide (15.0%) and 34 of 120 on placebo "
         "(28.3%), a risk ratio of 0.53 (95% CI 0.32 to 0.88). Mean growth velocity was 0.9 cm per year lower with budesonide "
         "(95% CI 0.4 to 1.4). Adherence by dose counter was 71% and did not differ between groups.",
         "Discussion", "Budesonide halved exacerbations but slowed growth modestly. We did not study children under 6 or those with "
         "obesity, and follow-up ended at one year, so the effect on final adult height is unknown. Whether intermittent dosing keeps the "
         "benefit with less growth effect was not tested.",
         "References", "1. Global Initiative for Asthma. Global strategy for asthma management and prevention. 2022.",
         "2. Smith J, Lee K. Inhaled corticosteroids and growth in children. Pediatrics. 2019;143:e20182018."]),
    "montelukast_cohort.pdf": (
        "Montelukast and neuropsychiatric events in children with asthma: a retrospective cohort",
        ["Abstract", "Background: Montelukast is widely prescribed for childhood asthma, yet reports of sleep disturbance and mood change "
         "have raised concern. We studied 18,400 children aged 5 to 17 years dispensed montelukast or an inhaled corticosteroid.",
         "Introduction", "Montelukast blocks the action of leukotrienes and is taken by mouth once a day, which many families find easier "
         "than an inhaler. Since 2020 regulators in several countries have added warnings about sleep disturbance, anxiety and low mood, "
         "based mainly on spontaneous reports. Spontaneous reports cannot show how common an event is or whether it exceeds the background "
         "rate in children with asthma, who already have more sleep and mood problems than other children. Controlled data are scarce, so "
         "clinicians have had little to tell parents beyond the warning itself. We therefore compared the rate of recorded sleep and mood "
         "diagnoses in children starting montelukast with the rate in children starting an inhaled corticosteroid, the usual alternative.",
         "Methods", "We used linked pharmacy and primary-care records from 2015 to 2020. The outcome was a recorded sleep or mood "
         "diagnosis within 90 days of the first dispensing. Confounding was handled with propensity-score weighting.",
         "Results", "Sleep or mood diagnoses were recorded for 2.1% of montelukast users and 1.4% of inhaled corticosteroid users, "
         "a weighted hazard ratio of 1.48 (95% CI 1.22 to 1.80). The excess was largest in the first 30 days. Children with prior "
         "anxiety were excluded from the main analysis.",
         "Discussion", "The signal is consistent with earlier reports, but residual confounding by asthma severity is possible and "
         "outcomes came from coded diagnoses, not validated scales. No data were available on children with prior anxiety or on "
         "long-term use beyond one year.",
         "References", "1. Global Initiative for Asthma. Global strategy for asthma management and prevention. 2022.",
         "2. Jones P, Patel R. Leukotriene antagonists and behaviour. Arch Dis Child. 2020;105:1-6."]),
}


def _env_key(name: str) -> str:
    if os.getenv(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _pdf(title: str, blocks: list[str]) -> bytes:
    """A one- or two-page PDF with real text. insert_textbox draws nothing, without an error, when text does not fit its box,
    so every box is generous and a paragraph that still does not fit fails the test at once."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    assert page.insert_textbox(pymupdf.Rect(50, y, 545, y + 60), title, fontsize=15, fontname="helv") >= 0
    y += 70
    heads = {"Abstract", "Introduction", "Methods", "Results", "Discussion", "References"}
    for b in blocks:
        size, height = (12, 24) if b in heads else (10, 14 * (len(b) // 80 + 1) + 12)
        if y + height > 800:
            page = doc.new_page()
            y = 50
        assert page.insert_textbox(pymupdf.Rect(50, y, 545, y + height), b, fontsize=size, fontname="helv") >= 0, f"did not fit: {b[:40]}"
        y += height
    return doc.tobytes()


def test_a_real_run_on_two_tiny_papers_completes_every_stage(isolated_env):
    key = _env_key("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY is not set")
    from pipeline import run_pipeline as rp
    from utils import database as db
    from utils.model_router import ModelRouter
    from utils.model_settings import recommend

    router = ModelRouter(recommend({"gemini"}), {"gemini": key})
    warnings, stages = [], []
    options = rp.RunOptions(provider_key="gemini", model=router.config.spec_for("analysis").model, token_cap=TOKEN_CAP)
    papers = [(name, _pdf(title, blocks)) for name, (title, blocks) in PAPERS.items()]
    outcome = rp.run_full_pipeline(papers, {"research_interest": "inhaled versus oral treatment for childhood asthma"}, router, options,
                                   name="real smoke", progress=lambda m, p: stages.append(m), warn=warnings.append)

    # every stage ran
    assert outcome.n_papers == 2 and outcome.run_id
    assert outcome.n_evidence >= 4, f"only {outcome.n_evidence} evidence items"
    assert outcome.n_gaps >= 1, "no research gap was found"
    res = outcome.results
    assert res.get("wiki") and res.get("graph") and res.get("gaps") is not None

    # the evidence is quoted and paged, and each quote really is in the source text
    sources = {n: "".join(blocks).lower() for n, (_t, blocks) in PAPERS.items()}
    flat = " ".join(sources.values())
    items = [e for ev in (res.get("evidence_objects") or {}).values() for e in ev]
    assert items
    prov = lambda e: e.get("provenance") or {}
    with_quote = [e for e in items if prov(e).get("quote")]
    assert len(with_quote) / len(items) >= 0.9, f"only {len(with_quote)} of {len(items)} evidence items carry a quote"
    assert all(prov(e).get("page") for e in with_quote), "a quoted item has no page"
    flat_norm = " ".join(flat.split())
    found = [e for e in with_quote if " ".join(str(prov(e)["quote"]).lower().split())[:60] in flat_norm]
    assert len(found) / len(with_quote) >= 0.8, f"only {len(found)} of {len(with_quote)} quotes are verbatim"

    # no call ended in a rate limit, and the run stayed inside its cap
    log = getattr(router, "call_log", None)
    records = getattr(log, "records", []) or []
    limited = [r for r in records if not r.get("ok") and r.get("error_kind") == "rate_limit"]
    assert not limited, f"{len(limited)} calls were rate limited (stages: {sorted({r['stage'] for r in limited})})"
    used = router.budget.used if router.budget else 0
    print(f"\nstages: {len(stages)} · calls: {len(records)} · tokens ≈ {used} · warnings: {len(warnings)}")
    assert used <= TOKEN_CAP

    # it was saved and opens again
    assert db.load_run(outcome.run_id)["results"]
