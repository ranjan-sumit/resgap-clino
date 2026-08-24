"""
Shared response models (Clinova Phase 5, Epic 5.1). Design principle,
binding across every model in this API: never emit a bare number, a bare
color, or a bare status word. Every value that carries meaning also
carries its label, its basis, and (when uncertain or absent) an honest
reason -- the server-side enforcement of 02-ux-specification.md §6/NFR-8
("never present a probabilistic or unresolved conclusion as certainty")
so no individual React component has to remember the rule.
"""
from typing import Literal

from pydantic import BaseModel

Tone = Literal["positive", "caution", "critical", "neutral", "unknown"]
Icon = Literal[
    "check-circle", "alert-triangle", "octagon-x", "circle-dashed",
    "help-circle", "shield-check", "search-x",
]


class StatusChip(BaseModel):
    """A status that must never be rendered as color alone. `label` is
    always human text; `icon` is a distinct shape per status family
    (e.g. INSUFFICIENT_EVIDENCE gets "search-x", never shared with
    OPEN's "check-circle"); `reason` is never empty, including for a
    clean pass ("why this passed" is still real information)."""
    code: str
    label: str
    tone: Tone
    icon: Icon
    reason: str


class Measure(BaseModel):
    """A confidence/quality value that can never be rendered as a bare
    percentage. `recorded=False` (not a fabricated 0.0) when nothing was
    measured -- `basis` always explains why, whether present or absent."""
    key: str
    label: str
    value: float | None = None
    display: str
    level: Literal["High", "Medium", "Low", "Unknown"]
    basis: str
    source: str
    recorded: bool
    status: StatusChip | None = None


class CountStat(BaseModel):
    key: str
    label: str
    value: int | None = None
    display: str
    recorded: bool
    source: str


class VersionField(BaseModel):
    key: str
    label: str
    value: str | None = None
    recorded: bool
    note: str | None = None


class RunRef(BaseModel):
    """A minimal, linkable reference to a run -- used wherever another
    model needs to point at "the run this came from" without embedding
    the full RunSummary."""
    run_id: str
    name: str
    created_at: str
