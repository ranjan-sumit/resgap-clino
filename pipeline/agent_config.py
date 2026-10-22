"""
AgentConfig (Clinova Phase 3, Epic 3.6, resolves the budgets/timeouts
half of PRD FR-19; ADR-006; 04-ai-research-architecture.md §3): typed,
enforced per-agent configuration -- a real object's fields, not scattered
ad hoc kwargs at each call site.

Honest scope -- what this deliberately does NOT do, and why:

- The architecture doc's full AgentConfig also names `input_schema`/
  `output_schema` (JSON Schema refs into packages/research-schemas) and
  a `model: ModelBundleRef` tied to the Run Manifest's version tracking
  (06-versioning-lineage-architecture.md). Run Manifests are Phase 4
  scope and don't exist yet in this codebase; packages/research-schemas
  isn't wired for runtime output validation. Both fields exist on
  AgentConfig below (so its shape matches the doc, and a future Phase 4
  pass can populate them for real) but are honestly `None` and
  unenforced today -- not faked with a placeholder that looks real.

- Of the five named agent roles (04-ai-research-architecture.md §3),
  only three have a real, single LLM call site to attach a config to
  today: Evidence Extractor (pipeline/evidence_extractor.py's
  extract_llm_evidence()), Gap Generator (pipeline/gap_detector.py's
  detect_gaps()), Gap Challenger (pipeline/gap_challenger.py's
  judge_candidates()). The other two are NOT retrofitted here
  speculatively: **Methodology Critic** has no corresponding LLM call
  anywhere in this codebase -- nothing reviews a candidate gap's
  methodology today, this is a real gap between the doc and the code,
  not an oversight in this file. **Research Chair** exists as
  pipeline/llm_council.py's chair/synthesis call, but only within the
  Computational Lab feature (statistical model selection for parameter
  simulation) -- a different, adjacent system from the gap-analysis
  pipeline the architecture doc's role table describes -- so it is
  named here for completeness but not wired into a gap-analysis call
  site that doesn't exist.

- Spawn-depth enforcement (§3: "No agent spawns another agent except
  the Research Chair, and only under a bounded, explicit
  uncertainty-threshold trigger... a hard cap, not a soft guideline,
  enforced by a spawn-depth counter") is real, tested scaffolding here
  (check_spawn_depth()) but is currently unused in production: no agent
  in this codebase spawns another agent yet, so the guard has nothing to
  guard. It's ready for whenever that trigger is built, not a decoration.

What IS real and enforced: `max_tokens`/`timeout_seconds`/`max_retries`
are now genuine per-call parameters on `utils.azure_client.AzureOpenAIClient
.chat()`/`chat_json()` (previously hardcoded module constants shared
identically by every caller) -- the three real call sites above now pass
their own AgentConfig's values instead of an inline literal, so a
config change in one place actually changes call behavior, and the
values below are inspectable/testable as data instead of buried in
scattered kwargs.

`timeout_seconds` specifically required a second fix beyond just adding
the parameter: a real bug found live (2026-08-22) -- the openai SDK's own
`timeout=` kwarg does NOT reliably bound TOTAL streaming duration. A real
call made with `timeout_seconds=1` completed successfully in 47.3s,
because NVIDIA NIM's response keeps sending periodic chunks that each
individually complete well under httpx's own per-read timeout, even
though the cumulative stream takes far longer. `utils/azure_client.py`'s
`_collect_stream()` now enforces a real wall-clock deadline check between
chunks -- confirmed live: the same reproduction now fails in 3.6s with a
`timeout`-classified Failure instead of silently running to completion.
Without that fix, `timeout_seconds` here would have been a field that
looked enforced but wasn't.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    role: str
    max_tokens: int
    timeout_seconds: int
    max_retries: int = 2
    max_requests: int = 1
    max_tool_calls: int = 0
    max_search_calls: int = 0
    allowed_tools: tuple = ()
    model: str = ""
    prompt_version: str = "1"
    # Honest None -- see module docstring's "does NOT do" section.
    input_schema: str | None = None
    output_schema: str | None = None


# Real, measured values already in production at each site, not
# invented here -- see each config's own comment for provenance.

# B30 fix (2026-09-08): timeout_seconds raised 120->300, max_retries 2->3
# on all three configs below. Real live evidence, not a guess: 4 real
# pipeline runs this session against the same 3-paper corpus each failed
# on a timeout, but at a DIFFERENT stage each time it got far enough to
# matter (Stage 6 proposal generation twice, then Stage 4 gap detection)
# -- ruling out a single slow call site and pointing instead at this
# NVIDIA account's endpoint being broadly slow/degraded right now,
# matching this codebase's own prior documented finding of the same
# symptom (module docstring above, and RESUME.md's B22 section: "master
# model took 38.3s then 230.1s for a trivial call"). 120s/2 retries
# (effectively ~1-2 real attempts before falling back) isn't enough
# margin under these conditions for ANY of the three real LLM call sites
# below, not just whichever one happened to fail first.
EVIDENCE_EXTRACTOR = AgentConfig(
    role="Evidence Extractor",
    # pipeline/evidence_extractor.py's extract_llm_evidence(): raised
    # 800->1500 (2026-08-21) to fit ~15 items across the 7 LLM-covered
    # evidence types without truncation -- see that file's own comment.
    max_tokens=1500,
    timeout_seconds=300,
    max_retries=3,
    model="openai/gpt-oss-20b",  # MASTER_MODEL, utils/azure_client.py
)

# Reads a whole paper (~15-20k tokens in) and returns up to ~45 quoted items, so the
# output budget is far above the wiki-based extractor's 1500.
EVIDENCE_READER = AgentConfig(
    role="Evidence Reader",
    max_tokens=12000,
    timeout_seconds=300,
    max_retries=2,
    prompt_version="2",
)

# The three gap-finder lenses (limitation miner, cross-paper synthesizer, methodology
# auditor) and the critic that scores, merges and ranks what they propose.
GAP_FINDER = AgentConfig(role="Gap Finder", max_tokens=6000, timeout_seconds=300, max_retries=2, prompt_version="2")
GAP_CRITIC = AgentConfig(role="Methodology Critic", max_tokens=8000, timeout_seconds=300, max_retries=2,
                         prompt_version="1")
PROPOSAL_REVIEWER = AgentConfig(role="Proposal Reviewer", max_tokens=10000, timeout_seconds=300, max_retries=2,
                                prompt_version="1")

GAP_GENERATOR = AgentConfig(
    role="Gap Generator",
    # pipeline/gap_detector.py's detect_gaps(): max_tokens unchanged from
    # its existing inline literal (4000) -- not a B24-style measured
    # token-budget bottleneck like graph extraction's 24000; this
    # session's real failure here was a plain wall-clock timeout, not a
    # truncated/malformed response, so only timeout_seconds/max_retries
    # needed raising (see B30 comment above).
    max_tokens=4000,
    timeout_seconds=300,
    max_retries=3,
    model="openai/gpt-oss-20b",
)

GAP_CHALLENGER = AgentConfig(
    role="Gap Challenger",
    # pipeline/gap_challenger.py's judge_candidates(): max_tokens
    # unchanged from its existing inline literal (2000), one scoped call
    # per gap, capped at max_candidates=8 -- see that file's own comment.
    max_tokens=2000,
    timeout_seconds=300,
    max_retries=3,
    max_search_calls=2,  # Semantic Scholar + arXiv, per query family
    model="openai/gpt-oss-20b",
)


_SPAWN_DEPTH_LIMIT = 1  # Research Chair -> one capped re-run, never open-ended (§3)


class SpawnDepthExceededError(Exception):
    """Raised by check_spawn_depth() when a proposed agent spawn would
    exceed §3's hard cap -- "never an open-ended recursive fan-out.\""""

    def __init__(self, depth: int):
        self.depth = depth
        super().__init__(
            f"Spawn depth {depth} exceeds the hard cap of {_SPAWN_DEPTH_LIMIT} "
            "(04-ai-research-architecture.md §3: one capped re-run, never open-ended)."
        )


def check_spawn_depth(current_depth: int) -> None:
    """Raises SpawnDepthExceededError if `current_depth` (the depth an
    agent spawn would reach, not the depth before spawning) exceeds the
    hard cap. No-op (returns None) otherwise. Call before any future
    agent-spawns-agent trigger is actually invoked -- unused today since
    no agent spawns another yet, see module docstring."""
    if current_depth > _SPAWN_DEPTH_LIMIT:
        raise SpawnDepthExceededError(current_depth)
