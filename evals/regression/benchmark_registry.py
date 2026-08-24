"""Registers evals/benchmarks/{version}/MANIFEST.json as a real
research_artifacts row (artifact_type='evaluation_benchmark', already a
legal value in migrations/0002_artifact_registry.sql's CHECK constraint --
no migration needed). This is an additive index over the existing
MANIFEST.json files, not a rewrite of either fixture format.
"""
import hashlib
import json
import os

from utils.database import record_artifact

BENCHMARK_PROJECT_ID = "_clinova_benchmark"
# Sentinel project_id: benchmark artifacts are cross-project by nature
# (evaluated against pipeline runs from any project), but
# research_artifacts.project_id is NOT NULL and the schema defines no
# separate convention for a non-project-scoped artifact. Documented here
# rather than left implicit.


def _manifest_path(version: str) -> str:
    return os.path.join(
        os.path.dirname(__file__), "..", "benchmarks", version, "MANIFEST.json"
    )


def register_benchmark_version(version: str, manifest_path: str = None) -> str:
    """Reads evals/benchmarks/{version}/MANIFEST.json and records it as a
    research_artifacts row. content_hash is over the manifest's case_id
    list (not the fixture files themselves) -- v2 is explicitly
    non-immutable/still evolving per its own MANIFEST.json note, so
    re-registering after a case is added/removed produces a genuinely new
    hash and a new logical version, matching
    06-versioning-lineage-architecture.md §2's immutability rule ("a
    correction or addition produces a new benchmark version").

    Registered directly at status='CHAMPION': benchmark artifacts are the
    yardstick evaluation is measured against, not a pipeline artifact
    under evaluation -- they are never run through the CANDIDATE/CHAMPION
    promotion gate that pipeline artifacts go through
    (evals/regression/promotion_gate.py). A deliberate, documented scope
    decision, not an oversight.

    Returns the artifact_id, e.g. "evaluation_benchmark:v1:<hash8>".
    """
    path = manifest_path or _manifest_path(version)
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)

    case_ids = sorted(manifest["cases"])
    content_hash = hashlib.sha256(
        json.dumps(case_ids, sort_keys=True).encode("utf-8")
    ).hexdigest()
    artifact_id = f"evaluation_benchmark:{version}:{content_hash[:8]}"

    record_artifact(
        artifact_id=artifact_id,
        artifact_type="evaluation_benchmark",
        artifact_version=version,
        project_id=BENCHMARK_PROJECT_ID,
        content_hash=content_hash,
        status="CHAMPION",
        metadata={
            "benchmark_version": manifest.get("benchmark_version", version),
            "cases": case_ids,
            "immutable": manifest.get("immutable"),
            "created": manifest.get("created"),
        },
    )
    return artifact_id
