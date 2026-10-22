"""
LLM Council — Redesigned for Novel Finding generation.
Council question changed from "interpret simulation" to
"what NEW thing have we discovered that no paper said?"

Council composition (NVIDIA NIM):
  Agent 1 — Dr. Statistician       → openai/gpt-oss-20b
  Agent 2 — Dr. Epidemiologist     → moonshotai/kimi-k3
  Agent 3 — Dr. Analyst/Critic     → nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
  Chair   — Consensus Synthesiser  → moonshotai/kimi-k3 (master)

B28/B29 fixes (2026-09-08), both found live, not assumed:
- Chair was openai/gpt-oss-120b -- NVIDIA end-of-life since 2026-09-03
  (live HTTP 410 Gone). Tried deepseek-ai/deepseek-v4-flash-0731 next; a
  live test call to it timed out (see utils/azure_client.py's MASTER_MODEL
  comment for the full story: this NVIDIA account is only entitled to a
  small fixed model allowlist, confirmed by live-testing 8 other
  candidates that all returned 404). Settled on moonshotai/kimi-k3 --
  live-tested HTTP 200, fast, and this account is confirmed entitled to
  it. Not yet independently re-verified in this Council-chair role
  specifically (its `has_reasoning: True`/streamed reasoning_content
  behavior here is inherited, not reconfirmed for this model) -- flagged,
  not hidden.
- Agent 2 was meta/llama-3.2-3b-instruct -- separately discovered dead
  (NVIDIA end-of-life since 2026-08-26, live HTTP 410) while live-testing
  candidates for the Chair fix above. This was broken independently of
  anything above; not previously noticed since nothing in this session had
  exercised the Council feature. Swapped to kimi-k3 for the same
  confirmed-entitled reason as the Chair; kept Agent 2's original low
  temperature (0.2) since that's a real tuned epidemiologist-role
  parameter, not tied to model identity.
"""
import json
import re
from openai import OpenAI

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

COUNCIL_MODELS = {
    "gpt_20b": {
        "model": "openai/gpt-oss-20b",
        "temperature": 1.0, "top_p": 1.0, "max_tokens": 4096,
        "extra_body": None, "has_reasoning": True,
    },
    "llama_3b": {
        # B29 fix (2026-09-08): meta/llama-3.2-3b-instruct is NVIDIA
        # end-of-life since 2026-08-26 (live HTTP 410) -- dict key kept as
        # "llama_3b" since MODEL_SELECTION_AGENTS references it by key.
        # top_p raised 0.7 -> 0.95 (kimi-k3 requirement, see module
        # docstring); temperature/max_tokens/has_reasoning are the real
        # tuned epidemiologist-role values, left unchanged.
        "model": "moonshotai/kimi-k3",
        "temperature": 0.2, "top_p": 0.95, "max_tokens": 1024,
        "extra_body": None, "has_reasoning": False,
    },
    "nemotron": {
        "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "temperature": 0.6, "top_p": 0.95, "max_tokens": 8192,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 4096,
        },
        "has_reasoning": True,
    },
    "gpt_120b": {
        # B28 fix (2026-09-08): openai/gpt-oss-120b is NVIDIA end-of-life
        # (410 Gone since 2026-09-03).
        # B29 fix (2026-09-08): tried deepseek-v4-flash-0731 next, but a
        # live test call to it timed out (see utils/azure_client.py's
        # MASTER_MODEL comment for the full account-entitlement story) --
        # swapped to moonshotai/kimi-k3 instead, live-tested HTTP 200 and
        # fast. kimi-k3 needs top_p=0.95, not the standard 1.0 (rejects it
        # with a 400) -- unlike utils/azure_client.py's shared client, this
        # file's _call_model() already reads top_p per-model from this
        # dict, so no separate override mechanism is needed here.
        # Dict key kept as "gpt_120b" since MODEL_SELECTION_AGENTS/the chair
        # call site below reference it by key, not by model string.
        "model": "moonshotai/kimi-k3",
        "temperature": 1.0, "top_p": 0.95, "max_tokens": 4096,
        "extra_body": None, "has_reasoning": True,
    },
}

MODEL_SELECTION_AGENTS = [
    {
        "name": "Dr. Statistician", "role": "Biostatistician", "model_key": "gpt_20b",
        "lens": (
            "You are a biostatistician. Assess which computational model(s) best fit "
            "the available parameters. Consider data types, CI coverage, and completeness. "
            "Be specific — name the model and justify with data evidence."
        ),
    },
    {
        "name": "Dr. Epidemiologist", "role": "Clinical Epidemiologist", "model_key": "llama_3b",
        "lens": (
            "You are a clinical epidemiologist. Assess population heterogeneity, "
            "study design compatibility, and whether parameters come from comparable populations. "
            "Flag mismatches that affect model validity."
        ),
    },
    {
        "name": "Dr. Analyst", "role": "Computational Research Analyst", "model_key": "nemotron",
        "lens": (
            "You are a computational analyst. Assess practical executability of each model. "
            "Which algorithms will the available data actually support? "
            "Recommend running MULTIPLE models if data allows — more algorithms = richer insight."
        ),
    },
]

INSIGHT_SYNTHESIS_AGENTS = [
    {
        "name": "Dr. Clinician", "role": "Clinical Practitioner", "model_key": "gpt_20b",
        "lens": (
            "You are a senior clinician. You have seen simulation results AND novel hypotheses "
            "generated by combining multiple papers. Your job: identify the single most clinically "
            "important NEW finding — something no individual paper said, that changes how "
            "a clinician should think about this condition. Be specific. Name exact numbers."
        ),
    },
    {
        "name": "Dr. Researcher", "role": "Research Scientist", "model_key": "llama_3b",
        "lens": (
            "You are a research scientist. You have simulation outputs and cross-paper hypotheses. "
            "Identify what is GENUINELY NEW from a research perspective — not a restatement "
            "of existing knowledge but an emergent finding from combining these papers. "
            "What study should be funded next, and why specifically?"
        ),
    },
    {
        "name": "Dr. Critic", "role": "Methodological Critic", "model_key": "nemotron",
        "lens": (
            "You are a rigorous methodological critic. Challenge the novel hypotheses and "
            "simulation findings. What assumptions could be wrong? Where is the evidence "
            "weakest? What would change the conclusion? Be harsh but constructive — "
            "stakeholders need to know what they can defend and what they cannot."
        ),
    },
]

CONSENSUS_PROMPT = """You are the Council Chair. Three specialists have debated.
Synthesise into a consensus.

Return ONLY JSON:
{
  "consensus": "clear summary of agreed recommendation",
  "key_points": ["3-5 points the council agrees on"],
  "disagreements": ["points where agents differed, and how resolved"],
  "confidence": "high|medium|low",
  "caveats": ["important limitations"]
}"""

MODEL_COUNCIL_FINAL_PROMPT = """Based on the council debate, produce the final model selection.

Return ONLY JSON:
{
  "selected_model": "monte_carlo|markov_chain|bayesian_network|survival_model|hybrid_monte_carlo_markov",
  "rationale": "2-3 sentence justification",
  "scenarios": ["Base Case", "Optimistic", "Conservative"],
  "population_notes": "any weighting needed",
  "key_parameters_to_use": ["parameter names"],
  "parameters_to_flag": ["problematic parameters"],
  "confidence": "high|medium|low",
  "alternative_if_insufficient": "fallback model"
}"""

INSIGHT_COUNCIL_FINAL_PROMPT = """The council has reviewed simulation results AND novel hypotheses
from cross-paper analysis. Produce the definitive finding report.

The output MUST contain at least one NEW FINDING — something that emerges from combining
these papers that no single paper stated. Do not produce vague statements.
Be specific: name interventions, populations and outcomes.

GROUNDING RULES:
- The new finding is a HYPOTHESIS to be tested, not a result. State the expected direction of the effect, NOT its size.
- NEVER state a percentage, fold-change, probability or threshold unless it appears in the hypotheses, simulation results or papers given above. If the size is unknown, write "magnitude unknown".
- Every entry in evidence_chain must be a finding that was actually given above. Do not introduce a mechanism, exposure or population the papers do not discuss; if the link is a stretch, say so and use "low" confidence.

Return ONLY JSON:
{
  "novel_finding": {
    "title": "Short specific title of the new finding",
    "claim": "Precise statement: [Intervention] in [Population] is expected to [increase|decrease|change] [Outcome] vs [comparator] (magnitude unknown unless given above)",
    "what_makes_it_new": "Specifically what no individual paper said",
    "evidence_chain": ["Paper X finding A supports this because...", "Paper Y finding B shows..."],
    "mechanism": "Biological/clinical mechanism making this plausible",
    "validation_study": "Specific study design: RCT|cohort, N~X, primary endpoint Y",
    "clinical_opportunity": "How this changes clinical practice",
    "commercial_opportunity": "Product, service, or patent potential",
    "confidence": "high|medium|low",
    "confidence_reasoning": "why this confidence level"
  },
  "clinical_insights": ["3-4 specific actionable insights for clinicians"],
  "research_insights": ["3-4 specific research directions with justification"],
  "simulation_interpretation": "What the multi-algorithm simulation reveals about uncertainty",
  "key_uncertainties": ["2-3 areas where evidence is weakest"],
  "actionable_next_steps": ["2-4 specific things to do: fund study X, apply for grant Y, etc."],
  "limitations": ["2-4 honest methodological limitations"],
  "overall_confidence": "high|medium|low"
}"""


def _call_model(api_key: str, model_key: str, system: str, user: str) -> str:
    cfg    = COUNCIL_MODELS[model_key]
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)
    kwargs = dict(
        model=cfg["model"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=cfg["temperature"],
        top_p=cfg["top_p"],
        max_tokens=cfg["max_tokens"],
        stream=True,
    )
    if cfg.get("extra_body"):
        kwargs["extra_body"] = cfg["extra_body"]

    parts = []
    try:
        stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not getattr(chunk, "choices", None):
                continue
            content = getattr(chunk.choices[0].delta, "content", None)
            if content:
                parts.append(content)
    except Exception as e:
        return {"_failed": True, "error": str(e), "model": cfg["model"]}
    return "".join(parts).strip()


def _robust_parse(raw: str, expected: type = dict):
    # The trailing-comma repair is deliberately LAST: applied to strict JSON
    # it can corrupt string values containing ",}" into wrong-but-parseable
    # output, so strict loads and brace-extraction get their chance first.
    for strategy in [
        lambda s: s,
        lambda s: re.sub(r'^```(?:json)?\s*|\s*```$', '', s).strip(),
    ]:
        try:
            result = json.loads(strategy(raw))
            if isinstance(result, expected):
                return result
        except Exception:
            pass
    for pattern, exp in [(r'\{.*\}', dict), (r'\[.*\]', list)]:
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group())
                if isinstance(result, expected):
                    return result
            except Exception:
                pass
    try:
        result = json.loads(re.sub(r',\s*([}\]])', r'\1', raw))
        if isinstance(result, expected):
            return result
    except Exception:
        pass
    return {} if expected == dict else []


class _LegacyBackend:
    """The original behaviour: every council seat is an NVIDIA model from
    COUNCIL_MODELS, called with one NVIDIA key. Used when no model router is
    supplied (existing callers and tests)."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def label(self, model_key: str) -> str:
        return COUNCIL_MODELS[model_key]["model"]

    def call(self, model_key: str, system: str, user: str):
        return _call_model(self.api_key, model_key, system, user)


def _backend_for(client) -> object:
    """The council backend for a client: a ModelRouter supplies one (each seat and
    the chair on whichever provider/model the user chose); a plain client falls
    back to the original NVIDIA-only table."""
    if hasattr(client, "council_backend"):
        return client.council_backend()
    return _LegacyBackend(getattr(client, "api_key", ""))


def run_council(agents: list, context: str, final_prompt: str,
                api_key: str = "", master_key: str = "gpt_120b", backend=None) -> dict:
    backend = backend or _LegacyBackend(api_key)
    agent_responses = []
    failures = []
    transcript_lines = []

    for agent in agents:
        system = (
            f"You are {agent['name']}, a {agent['role']} on a medical research council.\n\n"
            f"{agent['lens']}\n\n"
            "Be direct, specific, and evidence-based. Give 3-5 key points."
        )
        model_label = backend.label(agent["model_key"])
        response    = backend.call(agent["model_key"], system,
                                   f"Council context:\n\n{context}\n\nGive your expert assessment.")
        if isinstance(response, dict) and response.get("_failed"):
            # A failed call contributes no opinion: it is carried as
            # structured failure context, never as debate text the chair
            # could mistake for an agent's position.
            failures.append({
                "agent": agent["name"], "model": model_label,
                "error": response.get("error", "unknown error"),
            })
            agent_responses.append({
                "agent": agent["name"], "role": agent["role"],
                "model": model_label, "response": "",
                "failed": True, "error": response.get("error", ""),
            })
            transcript_lines.append(
                f"**{agent['name']} ({agent['role']}) [{model_label}]:\n"
                f"[CALL FAILED — no opinion available]"
            )
            continue
        agent_responses.append({
            "agent": agent["name"], "role": agent["role"],
            "model": model_label, "response": response,
        })
        transcript_lines.append(
            f"**{agent['name']} ({agent['role']}) [{model_label}]:**\n{response}"
        )

    debate_text = "\n\n---\n\n".join(
        f"{r['agent']} [{r['model']}]:\n"
        + (r["response"] if r.get("response") else "[CALL FAILED — no opinion available]")
        for r in agent_responses
    )
    failures_note = ""
    if failures:
        failures_note = (
            "\n\nThe following council member(s) could not be reached and provided "
            "NO opinion. Do not treat their absence as agreement or disagreement; "
            "synthesise consensus only from the responses present:\n"
            + "\n".join(f"- {f['agent']} [{f['model']}]: {f['error']}" for f in failures)
        )
    consensus_context = (
        f"Original context:\n{context}\n\nDebate:\n{debate_text}{failures_note}"
    )

    raw_consensus = backend.call(
        master_key,
        CONSENSUS_PROMPT + "\n\nReturn ONLY valid JSON.",
        consensus_context,
    )
    if isinstance(raw_consensus, dict):
        consensus = {"consensus": "", "key_points": [], "confidence": "medium",
                     "chair_error": raw_consensus.get("error", "")}
    else:
        consensus = _robust_parse(raw_consensus, dict)
        if not consensus:
            consensus = {"consensus": raw_consensus, "key_points": [], "confidence": "medium"}

    raw_final = backend.call(
        master_key,
        final_prompt + "\n\nReturn ONLY valid JSON.",
        f"{consensus_context}\n\nCouncil consensus:\n{json.dumps(consensus, indent=2)}",
    )
    if isinstance(raw_final, dict):
        final_decision = {"chair_error": raw_final.get("error", "")}
    else:
        final_decision = _robust_parse(raw_final, dict)
        if not final_decision:
            final_decision = {"decision": raw_final}

    return {
        "agents":          agent_responses,
        "consensus":       consensus,
        "final_decision":  final_decision,
        "transcript":      "\n\n".join(transcript_lines),
    }


def council_select_model(params: list, sufficiency: dict, context: dict, client) -> dict:
    backend = _backend_for(client)
    summary = {
        "total_parameters":   len(params),
        "categories_present": list(set(p.get("category", "") for p in params)),
        "params_with_ci":     sum(1 for p in params if p.get("ci_lower") is not None),
        "derived_params":     sum(1 for p in params if p.get("is_derived")),
        "sufficiency":        sufficiency,
        "sample_params": [
            {k: p.get(k) for k in ["name","category","value","ci_lower","ci_upper","confidence"]}
            for p in params[:8]
        ],
    }
    council_context = (
        f"Research domain: {context.get('domain','Healthcare AI')}\n"
        f"Researcher interest: {context.get('interest','')}\n\n"
        f"Extracted parameters:\n{json.dumps(summary, indent=2)}"
    )
    return run_council(MODEL_SELECTION_AGENTS, council_context, MODEL_COUNCIL_FINAL_PROMPT, backend=backend)


def council_synthesise_insights(
    sim_results: dict, discovery: dict,
    params: list, gaps: list, context: dict, client,
) -> dict:
    backend    = _backend_for(client)
    gap_titles = [g.get("title", "") for g in gaps[:5]]
    hypotheses = discovery.get("hypotheses", [])

    if sim_results.get("skipped"):
        simulation_block = (
            "SIMULATION RESULTS:\nNO SIMULATION WAS RUN. The papers did not contain enough quantitative "
            f"parameters ({sim_results.get('skip_reason', 'insufficient data')}). Base every insight on the "
            "hypotheses, the research gaps and what the papers actually report. Make NO numerical prediction, "
            "probability or effect size, and say plainly where the data are too thin to say more.\n\n")
    else:
        simulation_block = (
            f"SIMULATION RESULTS:\n"
            f"Models run: {sim_results.get('models_run', [sim_results.get('model_used','unknown')])}\n"
            f"Headline numbers: {json.dumps(sim_results.get('headline_numbers',{}), indent=2)}\n"
            f"Top sensitivity drivers: {json.dumps(sim_results.get('sensitivity_ranking',[])[:5], indent=2)}\n\n")
    council_context = (
        f"Research domain: {context.get('domain','Healthcare AI')}\n\n"
        f"NOVEL HYPOTHESES from cross-paper analysis:\n"
        f"{json.dumps(hypotheses[:3], indent=2)}\n\n"
        f"{simulation_block}"
        f"RESEARCH GAPS previously identified:\n{json.dumps(gap_titles, indent=2)}\n\n"
        f"Parameters used: {len(params)}"
    )
    return run_council(INSIGHT_SYNTHESIS_AGENTS, council_context, INSIGHT_COUNCIL_FINAL_PROMPT, backend=backend)
