---
name: 'Healthcare-AI Deterministic Gap-Pattern Library — Draft'
type: domain-reference
status: draft-needs-expert-review
created: '2026-08-21'
companions: ['04-ai-research-architecture.md']
---

# Healthcare-AI Deterministic Gap-Pattern Library (draft)

**Provenance and limits, stated up front:** this is Claude's best-effort draft, produced at the user's request in place of blocking on an unavailable clinical/biostatistics expert (`04-ai-research-architecture.md` §4's originally-flagged open question). It is grounded in recognized medical-AI methodology and reporting frameworks — **TRIPOD+AI** (prediction model reporting), **PROBAST** (risk-of-bias assessment for prediction models), **CONSORT-AI / SPIRIT-AI** (AI clinical trial reporting), and common systematic-review critique dimensions — not invented from scratch. It is **not** a substitute for review by an actual clinical researcher or biostatistician, especially before any pattern here is used to make a claim that could influence a real clinical-deployment or funding decision. Treat this as the Phase 3 starting point to hand to a domain expert for correction, not as pre-validated fact. Extends (does not replace) the 10-item starting set already in `04-ai-research-architecture.md` §4.

Each pattern states: what it detects (the trigger condition, checkable against Evidence Objects + wiki fields), why it's a genuine gap signal, and which `gap_type` it maps to (matching the existing `app.py` UI enum: Methodology, Application, Dataset, Evaluation, Theory, Benchmark).

## Study validity & generalizability

| Pattern | Trigger | Why it matters | gap_type |
|---|---|---|---|
| Missing external validation | No `DatasetPopulation` or `Method` evidence mentions a held-out cohort from a different institution/source than training data | Internal-only validation is the single most common reason a published medical-AI result fails to replicate (TRIPOD+AI item 13) | Evaluation |
| Single-center study | `DatasetPopulation` evidence names exactly one institution/site | Site-specific artifacts (scanner type, local population, clinical workflow) routinely inflate apparent performance | Dataset |
| Retrospective-only design | `StudyDesign` evidence states retrospective/observational with no prospective validation mentioned | Retrospective data has known biases (selection, label leakage from post-hoc chart review) prospective studies avoid | Methodology |
| No temporal/dataset-shift validation | No evidence mentions testing on data from a different time period than training data | Medical practice and patient populations drift; a model validated once may already be stale | Evaluation |
| Missing calibration assessment | `Metric` evidence lists only discrimination metrics (AUC, accuracy, sensitivity/specificity) with no calibration metric (calibration curve, Brier score) | A well-discriminating model can still be badly miscalibrated, which matters directly for clinical decision thresholds (PROBAST domain 4) | Evaluation |

## Population & fairness

| Pattern | Trigger | Why it matters | gap_type |
|---|---|---|---|
| Limited/non-diverse population | `DatasetPopulation` evidence describes a population skewed toward one ancestry/ethnicity/geography with no stated diversity | Directly the failure mode already found live in this project's own corpus (`evals/benchmarks/baseline/phase0-findings.md` — Phase 0's real papers were explicitly "largely European ancestry") | Dataset |
| Missing demographic subgroup analysis | Metrics are reported only in aggregate, no evidence breaks results down by sex/age/ethnicity/socioeconomic status | Aggregate performance can hide a model that fails badly for an underrepresented subgroup — a known, serious medical-AI fairness failure mode | Evaluation |
| No fairness/bias testing | No evidence mentions a fairness metric (demographic parity, equalized odds, subgroup calibration) or bias audit | Absence of any fairness framing at all is a stronger signal than a subgroup analysis that merely under-covers some groups | Evaluation |
| Small sample size relative to model complexity | `DatasetPopulation` gives a sample size with no accompanying power/sample-size justification, especially alongside a high-capacity model (deep learning) | Under-powered studies produce unstable estimates and overfit-prone models — a classic, well-documented medical-AI critique | Methodology |
| No missing-data handling described | No `Method` evidence describes how missing data was handled | Silent imputation or listwise deletion can introduce bias undetectable from the reported results alone | Methodology |

## Comparison & interpretability

| Pattern | Trigger | Why it matters | gap_type |
|---|---|---|---|
| Missing benchmark/baseline comparison | No `ComparatorBaseline` evidence exists, or it names only a trivial baseline (random, majority-class) | A model's real value is only visible relative to the current standard of care or a strong existing method, not a strawman | Benchmark |
| No comparison to clinical standard of care | `ComparatorBaseline` evidence exists but names only other ML models, never a clinician/existing clinical tool | The clinically relevant question is "better than current practice," not "better than a different algorithm" | Application |
| No explainability/interpretability analysis | No evidence mentions feature importance, attention visualization, SHAP/LIME, or an equivalent interpretability method, for a black-box model class | Regulatory and clinical-adoption pathways for opaque models increasingly require some interpretability account | Methodology |
| Named methodological limitation (self-reported) | The paper's own `Limitation` evidence exists (already implemented, existing pattern) | The paper already admits a real gap in its own words — highest-confidence, lowest-risk pattern in the library | (inherits the limitation's own likely type) |

## Deployment & real-world evidence

| Pattern | Trigger | Why it matters | gap_type |
|---|---|---|---|
| No prospective/real-world deployment evidence | All evidence is retrospective/offline evaluation, no `FutureWork` or `Result` evidence describes a live clinical pilot | The gap between offline validation and real clinical workflow integration is a widely-documented failure point for medical AI | Application |
| No cost-effectiveness or workflow-impact analysis | No evidence addresses computational cost, clinician time impact, or health-economic outcome | Even an accurate model can fail adoption if it doesn't fit clinical workflow or isn't cost-justified | Application |
| No regulatory/safety framing | No evidence mentions a regulatory pathway (FDA/CE marking equivalent), safety monitoring plan, or failure-mode analysis | For anything positioned toward clinical use, absence of this framing is itself a real, reportable gap | Application |

## Data & reproducibility

| Pattern | Trigger | Why it matters | gap_type |
|---|---|---|---|
| No data/code availability statement | No evidence or wiki field mentions open data, open code, or a data-access process | Directly blocks external validation by anyone else — compounds the "missing external validation" pattern above | Methodology |
| Ambiguous/unreported class imbalance handling | `Metric`/`DatasetPopulation` evidence implies a skewed outcome prevalence with no evidence of imbalance-aware evaluation (e.g., PR-AUC alongside ROC-AUC, class weighting) | A model can score well on ROC-AUC on an imbalanced task while being clinically useless — a common, checkable pattern | Evaluation |

## How this plugs into the Hybrid Gap Engine

Per `04-ai-research-architecture.md` §4, these are the **deterministic pattern library** signal source — evaluated directly against a paper's Evidence Objects (Phase 2) and wiki fields, no LLM call required for the trigger check itself. A pattern firing produces a *candidate* gap, combined with the graph-structural and semantic-reasoning signals before becoming a reportable gap — this library alone is not sufficient to assert novelty (that's the Gap Challenger's job, Phase 3).

## Explicit non-goals of this draft

- Not exhaustive — deliberately scoped to patterns checkable from the Evidence Object types this project already extracts (Phase 2), not a general medical-AI critique taxonomy.
- Not weighted or prioritized — Phase 3 implementation needs to decide which patterns matter most for a given domain configuration (`domain_config.py`'s existing per-domain mechanism is the natural place for this).
- Not validated against real papers yet — unlike the rest of this session's work, these patterns have **not** been run against the real `Data-17072026/` corpus to confirm they actually fire correctly. That validation is real, necessary Phase 3 work, not done here.
