"""
Evidence Object schema (Clinova Phase 2, Story 2.1.2): the structured,
provenance-carrying scientific-claim representation 05-data-architecture.md
§8 specifies. This is meant to become the source of truth the knowledge
graph and gap engine read (Phase 3), instead of unstructured wiki-synthesis
text -- the direct fix for Problem A's "do not use summaries as the only
scientific source of truth."

One schema, imported everywhere an Evidence Object is created or checked
(pipeline/evidence_extractor.py, its tests, and any future Phase 3
consumer) -- never redefined ad hoc per caller.
"""
import hashlib
from dataclasses import dataclass, field, asdict

EVIDENCE_OBJECT_VERSION = 1

# 05-data-architecture.md §8's exact 13-value list.
EVIDENCE_TYPES = (
    "ResearchQuestion", "Problem", "StudyDesign", "DatasetPopulation",
    "InterventionModel", "ComparatorBaseline", "Method", "Metric",
    "Result", "Finding", "Limitation", "FutureWork", "Claim",
)

CONFIDENCE_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class Provenance:
    page: int | None            # real page number (Docling text_segments) or None -- never guessed
    section: str | None
    text_span: tuple[int, int] | None
    extraction_version: int = EVIDENCE_OBJECT_VERSION


@dataclass(frozen=True)
class EvidenceObject:
    evidence_type: str
    paper_id: str
    text: str
    provenance: Provenance
    confidence: str
    evidence_id: str = field(default="")
    evidence_object_version: int = EVIDENCE_OBJECT_VERSION

    def __post_init__(self):
        if self.evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"invalid evidence_type: {self.evidence_type!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"invalid confidence: {self.confidence!r}")
        if not self.text or not self.text.strip():
            raise ValueError("evidence text must be non-empty")
        if not self.evidence_id:
            # Content-addressed, matching the project-wide SHA-256
            # cache-key convention (AD-3) -- the same (paper_id,
            # evidence_type, text) always yields the same evidence_id,
            # which is what makes Story 2.2.1's caching correct.
            object.__setattr__(self, "evidence_id", _compute_evidence_id(
                self.paper_id, self.evidence_type, self.text,
            ))


def _compute_evidence_id(paper_id: str, evidence_type: str, text: str) -> str:
    return hashlib.sha256(f"{paper_id}:{evidence_type}:{text}".encode()).hexdigest()


def to_dict(obj: EvidenceObject) -> dict:
    return {
        "evidence_id": obj.evidence_id,
        "evidence_type": obj.evidence_type,
        "paper_id": obj.paper_id,
        "text": obj.text,
        "provenance": asdict(obj.provenance),
        "confidence": obj.confidence,
        "evidence_object_version": obj.evidence_object_version,
    }


def validate_evidence_dict(d: dict) -> bool:
    """Returns True if `d` has the minimum valid shape for an Evidence
    Object as it would come back from a raw LLM extraction -- used by
    pipeline/evidence_extractor.py to filter malformed items before
    acceptance (Story 2.1.4), without needing to fully construct an
    EvidenceObject just to find out it's invalid."""
    if not isinstance(d, dict):
        return False
    if d.get("evidence_type") not in EVIDENCE_TYPES:
        return False
    if d.get("confidence") not in CONFIDENCE_LEVELS:
        return False
    text = d.get("text")
    if not isinstance(text, str) or not text.strip():
        return False
    return True
