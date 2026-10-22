"""
Turns the feedback users give on a project's gaps and runs into text a prompt
can carry -- the hook for giving that feedback to the Gap Challenger judge and
to the agents (gap generator, evidence extractor) later.

NOT wired into any prompt yet, on purpose: feedback is captured and stored now,
and these functions are the stable, tested seam the judge/agents will call
(`build_feedback_context(project_id, role="judge")`) when that work is done.

Feedback is keyed by the stable gap_id (packages/research_schemas/gap_identity),
so a verdict on a gap in one run is still found when the same gap reappears in
a later run of the project. If a gap has feedback in several runs, only the
newest counts.

Roles, because a verdict means different things to different consumers:
  judge  - decides whether published literature already closes a gap, so it
           gets the reasons about the literature and evidence
           (REASON_ALREADY_ADDRESSED, REASON_WEAK_EVIDENCE) -- "humans consider
           this one closed / unsupported".
  agent  - generates gaps, so it gets what a good vs poor gap looks like for
           this project (useful, not relevant, too vague) plus run notes.
  all    - everything.

The text is user-written, so it is labelled as guidance, trimmed, and flattened
to single lines -- never presented to a model as instructions or facts.
"""
from utils import database as db

REASON_USEFUL = "Useful and well supported"
REASON_ALREADY_ADDRESSED = "Already addressed in the literature"
REASON_NOT_RELEVANT = "Not relevant to my project"
REASON_WEAK_EVIDENCE = "Evidence is weak or wrong"
REASON_TOO_VAGUE = "Too vague"
REASON_OTHER = "Other"

# Shown in the UI, in this order.
POSITIVE_REASONS = (REASON_USEFUL, REASON_OTHER)
NEGATIVE_REASONS = (REASON_ALREADY_ADDRESSED, REASON_NOT_RELEVANT, REASON_WEAK_EVIDENCE,
                    REASON_TOO_VAGUE, REASON_OTHER)

_JUDGE_REASONS = {REASON_ALREADY_ADDRESSED, REASON_WEAK_EVIDENCE}
_MAX_COMMENT_CHARS = 300
_MAX_TITLE_CHARS = 140

ROLES = ("judge", "agent", "all")


def _flat(text: str, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


def _latest_per_gap(rows: list[dict]) -> list[dict]:
    """rows arrive newest-first; keep the first row seen per gap_id."""
    seen, out = set(), []
    for r in rows:
        if r["target_type"] != "gap":
            continue
        if r["target_id"] in seen:
            continue
        seen.add(r["target_id"])
        out.append(r)
    return out


def get_feedback_items(project_id: str, role: str = "all", *, max_items: int = 20) -> list[dict]:
    """Structured feedback for a role: a list of {kind, gap_id, title, rating,
    reason, comment, run_id, updated_at}, newest first, gaps de-duplicated across
    runs. `kind` is "gap" or "run"."""
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; expected one of {ROLES}")
    rows = db.list_feedback(project_id=project_id)
    items = []

    for r in _latest_per_gap(rows):
        reason = r["reason"] or ""
        if role == "judge" and reason not in _JUDGE_REASONS:
            continue
        if role == "agent" and reason in _JUDGE_REASONS:
            continue
        items.append({"kind": "gap", "gap_id": r["target_id"], "title": r["target_label"] or r["target_id"],
                      "rating": r["rating"], "reason": reason, "comment": r["comment"] or "",
                      "run_id": r["run_id"], "updated_at": r["updated_at"]})

    if role in ("agent", "all"):
        for r in rows:
            if r["target_type"] == "run" and (r["comment"] or r["rating"] is not None):
                items.append({"kind": "run", "gap_id": "", "title": "Overall analysis",
                              "rating": r["rating"], "reason": r["reason"] or "", "comment": r["comment"] or "",
                              "run_id": r["run_id"], "updated_at": r["updated_at"]})

    items.sort(key=lambda i: i["updated_at"], reverse=True)
    return items[:max_items]


def build_feedback_context(project_id: str, role: str = "all", *, max_items: int = 20,
                           max_chars: int = 3000) -> str:
    """The feedback as prompt-ready text, or "" if there is none. Never longer
    than `max_chars` (whole lines are dropped, never cut mid-line)."""
    items = get_feedback_items(project_id, role, max_items=max_items)
    if not items:
        return ""
    lines = ["Researcher feedback from earlier analyses in this project "
             "(guidance from the user, not established fact):"]
    for it in items:
        verdict = {1: "marked useful", -1: "marked not useful"}.get(it["rating"], "noted")
        reason = f" ({it['reason']})" if it["reason"] else ""
        comment = f': "{_flat(it["comment"], _MAX_COMMENT_CHARS)}"' if it["comment"] else ""
        lines.append(f'- "{_flat(it["title"], _MAX_TITLE_CHARS)}" {verdict}{reason}{comment}')

    out, size = [], 0
    for line in lines:
        if size + len(line) + 1 > max_chars:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out) if len(out) > 1 else ""
