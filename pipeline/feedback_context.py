"""
Turns the feedback users give on a project's gaps and runs into text a prompt
can carry -- the hook for giving that feedback to the Gap Challenger judge and
to the agents (gap generator, evidence extractor) later.

Wired into the gap critic and the proposal reviewer (prompt text) and into gap ranking
(`feedback_adjustment`: a gap like one the user marked not useful is ranked lower, one like a
useful gap slightly higher). The pipeline records in its trace what feedback was applied.

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


# ── effect on ranking ──────────────────────────────────────────────────────────────────────
_SIMILAR = 0.6              # word-overlap (Jaccard) at which two gap titles are "the same kind of gap"
PENALTY = -1.0
BOOST = 0.5
_MAX_PENALTY, _MAX_BOOST = -1.5, 1.0


def _title_words(text: str) -> set:
    import re
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3}


def feedback_adjustment(gap_title: str, items: list[dict]) -> tuple[float, str]:
    """(score change, note) for a gap, from earlier ratings of similar gaps in this project.
    Negative ratings lower the score, positive ones raise it a little; the total is capped so
    feedback steers the ranking without ever deciding it alone."""
    words = _title_words(gap_title)
    if not words:
        return 0.0, ""
    delta, notes = 0.0, []
    for it in items:
        if it.get("kind") != "gap" or it.get("rating") not in (1, -1):
            continue
        other = _title_words(it.get("title", ""))
        if not other or len(words & other) / len(words | other) < _SIMILAR:
            continue
        if it["rating"] == -1:
            delta += PENALTY
            notes.append(f"similar to a gap you marked not useful ({it.get('reason') or 'no reason'})")
        else:
            delta += BOOST
            notes.append("similar to a gap you marked useful")
    delta = max(_MAX_PENALTY, min(_MAX_BOOST, delta))
    return delta, "; ".join(dict.fromkeys(notes))
