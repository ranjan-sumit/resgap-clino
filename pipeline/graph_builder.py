"""
Stage 4: Knowledge Graph Builder — LazyGraphRAG style
Fixed bugs:
  1. Robust multi-strategy JSON parser (no more silent failures)
  2. Entity ID + name dual-lookup in orphan detection
  3. Token limit raised to 6000
  4. Network diagram data prepared for plotly
  13. build_knowledge_graph distinguishes a failed LLM call from a genuine
      empty extraction, and no longer risks an uncaught crash from the
      community-detection call on any path (see B13 fix comments below)
"""
import hashlib
import json
import re
from collections import defaultdict
from domain_config import inject_domain_into_graph_prompt
from utils.azure_client import unwrap, LLMCallError
from pipeline.evidence_linker import EVIDENCE_LINK_VERSION, build_paper_index, match_evidence_ids, resolve_paper_id

ENTITY_EXTRACTION_PROMPT = """You are a knowledge graph builder for research papers.

Given wiki pages from multiple research papers, extract:
1. Named entities: concepts, methods, datasets, metrics, problems, domains
2. Relationships between entities

Return ONLY a JSON object (no markdown, no explanation):
{
  "entities": [
    {
      "id": "unique_snake_case_id",
      "name": "Human readable name",
      "type": "concept|method|dataset|metric|problem|domain|model",
      "papers": ["paper titles that mention this entity"],
      "importance": "high|medium|low"
    }
  ],
  "relationships": [
    {
      "source": "entity_id",
      "target": "entity_id",
      "relation": "extends|contradicts|evaluates_on|applied_to|compared_with|is_limited_by|enables|ignores",
      "paper": "paper title where this relationship appears",
      "evidence": "brief quote or paraphrase supporting this relationship"
    }
  ]
}"""

COMMUNITY_PROMPT = """You are a research analyst identifying thematic communities in a knowledge graph.

Given entities and relationships from research papers, group them into thematic communities.

Return ONLY a JSON array:
[
  {
    "id": "community_1",
    "theme": "Short theme name",
    "entities": ["entity_id_1", "entity_id_2"],
    "summary": "2-3 sentence summary of what this community represents",
    "gap_signal": "Any gaps or missing connections suggested by this community"
  }
]"""


_MIN_ENTITIES_PER_PAPER = 8


def _robust_parse(raw: str, expected: type = dict):
    """
    Multi-strategy JSON parser. Tries 5 strategies before giving up.
    Returns empty dict/list on complete failure — never crashes.
    """
    if not raw:
        return {} if expected == dict else []

    strategies = [
        # 1: direct parse
        lambda s: s,
        # 2: strip markdown fences
        lambda s: re.sub(r'^```(?:json)?\s*|\s*```$', '', s).strip(),
        # 3: remove trailing commas before ] or }
        lambda s: re.sub(r',\s*([}\]])', r'\1', s),
        # 4: extract first {...} block
        lambda s: (re.search(r'\{.*\}', s, re.DOTALL) or type('', (), {'group': lambda self: ''})()).group(),
        # 5: extract first [...] block
        lambda s: (re.search(r'\[.*\]', s, re.DOTALL) or type('', (), {'group': lambda self: ''})()).group(),
    ]

    for strategy in strategies:
        try:
            candidate = strategy(raw)
            if candidate:
                result = json.loads(candidate)
                if isinstance(result, expected):
                    return result
        except Exception:
            continue

    return {} if expected == dict else []


# The Healthcare-AI vocabulary (model_architecture, clinical_task, predicts, diagnoses,
# validated_on...) describes machine-learning studies on patients. Forced onto a corpus of
# lab, review and survey papers it mislabels things (a survey became a "clinical_task", a
# statistical test a "clinical_metric", "Phe508del diagnoses Cystic Fibrosis").
_ML_STUDY_TYPES = ("ml_prediction_model", "computational_simulation")

_SCIENCE_VOCABULARY = """

ENTITY TYPES to use (pick the most specific): disease, condition, intervention (a drug, therapy or procedure), target (a gene, protein or pathway), biomarker, method, model_system (a cell model, organ-on-chip, animal model), organism, dataset_or_cohort, outcome_measure, concept.
- A statistical test is a method, not a metric. A survey or questionnaire is a method (or a dataset_or_cohort), never a task. A microorganism is an organism.
RELATIONSHIP TYPES to use: treats, targets, causes, associated_with, measured_by, studied_in, modeled_by, compared_with, contradicts, extends, enables, limited_by, requires, validated_on.
- Use "predicts" or "diagnoses" ONLY when a paper builds a predictive or diagnostic model. Prefer the specific relation ("treats", "targets", "measured_by") over the generic "applied_to".
"""


def _vocabulary_prompt(base_prompt: str, domain_config: dict, evidence_objects: dict | None) -> str:
    """The graph prompt with the domain vocabulary that fits the corpus: the configured
    (Healthcare-AI) one only when a paper is an ML / simulation study, otherwise a general
    biomedical-science vocabulary."""
    from pipeline.evidence_reader import study_type_of
    types = {study_type_of(items) for items in (evidence_objects or {}).values()} - {None}
    if types and not (types & set(_ML_STUDY_TYPES)):
        return base_prompt + _SCIENCE_VOCABULARY
    return inject_domain_into_graph_prompt(base_prompt, domain_config or {})


def extract_entities_and_relations(wiki: dict, client, domain_config: dict = None,
                                   evidence_objects: dict = None) -> dict:
    pages = wiki.get("pages", [])
    cross_links = wiki.get("cross_links", {})

    compact_wiki = []
    for p in pages:
        compact_wiki.append({
            "title": p.get("title", p.get("source_file", "Unknown")),
            "methods": p.get("methods", []),
            "key_concepts": p.get("key_concepts", []),
            "limitations": p.get("limitations", []),
            "future_work": p.get("future_work", []),
            "datasets": p.get("datasets", []),
            "key_findings": p.get("key_findings", []),
        })

    user_prompt = f"""Wiki pages from {len(pages)} research papers:

{json.dumps(compact_wiki, indent=2)}

Cross-paper connections already identified:
{json.dumps(cross_links, indent=2)}

Extract all entities and relationships for the knowledge graph.

Coverage rules (a sparse graph is a failure):
- Give EVERY paper at least {_MIN_ENTITIES_PER_PAPER} entities, drawn from its key_concepts, methods, datasets and findings. Use short, specific names.
- Every entity must appear in at least one relationship. Do not return isolated entities.
- Include at least {len(pages)} relationships that connect entities from DIFFERENT papers (shared concepts, contrasting methods, a dataset used by one paper and discussed by another).
- Use ONLY the relation values and type values listed in the schema.
- Give each relationship a short "evidence" phrase taken from the wiki text.
IMPORTANT: Return ONLY valid JSON — no text before or after."""

    system_prompt = _vocabulary_prompt(ENTITY_EXTRACTION_PROMPT, domain_config or {}, evidence_objects)

    # B24 fix (2026-08-21): max_tokens was 6000. Measured live against a real
    # 2-paper corpus: gpt-oss models are "thinking" models that stream a
    # reasoning_content phase before any real content -- on this prompt's
    # complexity, reasoning alone measured ~6300 tokens, consuming the ENTIRE
    # 6000-token budget before the model ever started the actual JSON answer
    # (finish_reason="length", content="", NOT a parse failure -- a genuinely
    # empty response that unconditionally fell back to the deterministic
    # graph every single time, for every historical run checked). Reproduced
    # identically on both openai/gpt-oss-120b and openai/gpt-oss-20b -- not a
    # bigger-model-specific problem, a token-budget-too-small-for-reasoning
    # problem. 16000 was measured just barely sufficient for reasoning
    # (~11000 tokens) + full content (~6000 tokens) to both complete
    # (finish_reason="stop") on that same real corpus; 24000 leaves real
    # margin for a larger corpus rather than being exactly enough for the one
    # test case measured.
    raw = unwrap(client.chat_json(system_prompt, user_prompt, max_tokens=24000))
    graph_data = _robust_parse(raw, dict)

    # B24 fix: retry once on a genuine parse failure before accepting it --
    # mirrors gap_detector.py's B19 retry-once pattern. A parse failure here
    # (raw was non-empty but no strategy produced a dict with real keys) is
    # distinct from a raw="" reasoning-exhaustion failure the max_tokens bump
    # above already targets, but both are worth one retry: a single LLM
    # sample occasionally emits syntactically invalid JSON (a missing comma
    # mid-object, measured live on this same prompt) that a second sample at
    # the same temperature is not guaranteed to repeat.
    parse_failed = "entities" not in graph_data and "relationships" not in graph_data
    if parse_failed:
        raw_retry = unwrap(client.chat_json(system_prompt, user_prompt, max_tokens=24000))
        retry_data = _robust_parse(raw_retry, dict)
        if "entities" in retry_data or "relationships" in retry_data:
            raw, graph_data = raw_retry, retry_data

    graph_data["_raw_response_preview"] = raw[:1000] if raw else ""
    graph_data["_used_fallback"] = False

    # Ensure correct structure
    if "entities" not in graph_data:
        graph_data["entities"] = []
    if "relationships" not in graph_data:
        graph_data["relationships"] = []

    return graph_data


def _assign_relationship_ids(graph_data: dict) -> None:
    """Clinova Phase 4, Epic 4.4 (Scientific Lineage plumbing): no
    relationship_id field exists in the LLM's schema (ENTITY_EXTRACTION_
    PROMPT above is deliberately left byte-identical -- the B24 max_tokens/
    reasoning-budget fix was live-measured against this exact prompt, and
    asking the LLM to invent ids would produce non-deterministic,
    unverifiable ones). Assigned post-hoc instead, deterministically, from
    the relationship's own content -- covers both the LLM extraction path
    and _fallback_graph_from_wiki() in one place, since this is called
    after graph_data settles regardless of which path produced it.
    Mutates graph_data["relationships"] in place."""
    seen: dict = {}
    for rel in graph_data.get("relationships", []):
        base = hashlib.sha256(
            f"{rel.get('source','')}:{rel.get('relation','')}:"
            f"{rel.get('target','')}:{rel.get('paper','')}".encode("utf-8")
        ).hexdigest()
        n = seen.get(base, 0)
        seen[base] = n + 1
        rel["relationship_id"] = base if n == 0 else f"{base}:{n}"


def _link_relationship_evidence(graph_data: dict, wiki: dict, evidence_objects: dict) -> dict:
    """Clinova Phase 4, Epic 4.4: repairs the real units mismatch between
    a relationship's "paper" field (an LLM-written paper TITLE) and
    EvidenceObject.paper_id (a filename) -- build_paper_index()/
    resolve_paper_id() are the translation layer. Each relationship gets
    a real provenance_evidence_ids list (honestly [] when nothing
    resolves, never a best-guess). Returns diagnostics counts."""
    paper_index = build_paper_index(wiki)
    relationships_with_evidence = 0
    paper_titles_unresolved = 0
    for rel in graph_data.get("relationships", []):
        paper_ref = rel.get("paper", "")
        resolved_paper_id = resolve_paper_id(paper_ref, paper_index)
        if paper_ref and resolved_paper_id is None:
            paper_titles_unresolved += 1
        rel["provenance_evidence_ids"] = match_evidence_ids(
            rel.get("evidence", ""), resolved_paper_id, evidence_objects,
        )
        if rel["provenance_evidence_ids"]:
            relationships_with_evidence += 1
    return {
        "relationships_total": len(graph_data.get("relationships", [])),
        "relationships_with_evidence": relationships_with_evidence,
        "paper_titles_unresolved": paper_titles_unresolved,
        "link_version": EVIDENCE_LINK_VERSION,
    }


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', str(value or "").lower()).strip('_')
    return slug[:80] or fallback


def _fallback_graph_from_wiki(wiki: dict) -> dict:
    """Deterministic graph when LLM extraction fails."""
    entities = []
    relationships = []
    seen = {}

    def add_entity(name, etype, paper_title, importance="medium"):
        if not name:
            return None
        key = _slug(name, f"entity_{len(entities)+1}")
        if key not in seen:
            seen[key] = {
                "id": key,
                "name": str(name)[:140],
                "type": etype,
                "papers": [],
                "importance": importance,
            }
            entities.append(seen[key])
        if paper_title and paper_title not in seen[key]["papers"]:
            seen[key]["papers"].append(paper_title)
        return key

    field_types = [
        ("key_concepts", "concept", "high"),
        ("methods", "method", "high"),
        ("datasets", "dataset", "medium"),
        ("evaluated_on", "metric", "medium"),
        ("limitations", "problem", "medium"),
        ("key_findings", "concept", "medium"),
    ]

    for page in wiki.get("pages", []):
        title = page.get("title") or page.get("source_file") or "Unknown paper"
        paper_id = add_entity(title, "domain", title, "high")
        for field, etype, importance in field_types:
            for item in page.get(field, [])[:10]:
                entity_id = add_entity(item, etype, title, importance)
                if paper_id and entity_id and paper_id != entity_id:
                    relationships.append({
                        "source": paper_id,
                        "target": entity_id,
                        "relation": "mentions",
                        "paper": title,
                        "evidence": f"Fallback graph linked {field} item from wiki extraction.",
                    })

    return {
        "entities": entities,
        "relationships": relationships,
        "_used_fallback": True,
        "_raw_response_preview": "",
    }


def build_communities(graph_data: dict, client) -> list:
    entities = graph_data.get("entities", [])
    relationships = graph_data.get("relationships", [])

    if not entities:
        return []  # B2 fix — was bare `return` which returns None, crashing callers []

    user_prompt = f"""Knowledge graph with {len(entities)} entities and {len(relationships)} relationships:

ENTITIES:
{json.dumps(entities[:60], indent=2)}

RELATIONSHIPS:
{json.dumps(relationships[:80], indent=2)}

Group into 3-6 thematic communities. Focus on identifying communities where gaps exist.
Return ONLY valid JSON array."""

    # B24 fix (2026-08-21): bumped 3000 -> 8000, same reasoning-budget-
    # exhaustion risk as extract_entities_and_relations() above (this call
    # wasn't directly measured hitting it, but shares the same "thinking
    # model, reasoning phase consumes the token budget before content"
    # mechanism on a prompt of comparable complexity -- entities[:60] +
    # relationships[:80] is not small). No retry-on-parse-failure here:
    # build_knowledge_graph() already treats an empty communities list as a
    # legitimate degrade-gracefully outcome (B13), not a hard failure worth
    # spending a second live call on.
    raw = unwrap(client.chat_json(COMMUNITY_PROMPT, user_prompt, max_tokens=8000))
    communities = _robust_parse(raw, list)
    return communities if isinstance(communities, list) else []


def find_orphan_concepts(graph_data: dict, wiki: dict) -> list:
    """
    Fixed: dual-lookup by entity ID AND name so relationships
    written with names (not IDs) are still matched correctly.
    """
    entities = graph_data.get("entities", [])
    relationships = graph_data.get("relationships", [])

    # Build lookup: id → entity, name_lower → entity
    entity_by_id   = {e.get("id", ""): e for e in entities}
    entity_by_name = {e.get("name", "").lower(): e for e in entities}

    # Count connections — match on both ID and name
    connection_count = defaultdict(int)
    for rel in relationships:
        for ref in [rel.get("source", ""), rel.get("target", "")]:
            ref_lower = ref.lower()
            if ref in entity_by_id:
                connection_count[entity_by_id[ref].get("id", ref)] += 1
            elif ref_lower in entity_by_name:
                matched = entity_by_name[ref_lower]
                connection_count[matched.get("id", ref_lower)] += 1

    orphans = []
    for entity in entities:
        eid = entity.get("id", "")
        connections = connection_count.get(eid, 0)
        papers = entity.get("papers", [])
        if (connections <= 1
                and entity.get("importance") in ["high", "medium"]
                and len(papers) <= 1):
            orphans.append({
                "entity": entity,
                "connections": connections,
                "signal": (
                    f"'{entity.get('name','')}' appears in only one paper "
                    f"with minimal cross-paper connections — potential unexplored area"
                ),
            })

    return orphans


def find_missing_bridges(graph_data: dict, wiki: dict) -> list:
    cross_links = wiki.get("cross_links", {})
    bridges = []
    for b in cross_links.get("limitation_bridges", []):
        bridges.append({
            "type": "limitation_bridge",
            "description": (
                f"'{b.get('limitation')}' in {b.get('limitation_in')} "
                f"could be addressed by {b.get('solution')} "
                f"from {b.get('potential_solution_in')}"
            ),
            "source_paper": b.get("limitation_in"),
            "target_paper": b.get("potential_solution_in"),
        })
    return bridges


def layout_positions(n: int, edges: list, seed: int = 7, iterations: int = 300) -> list:
    """Force-directed (Fruchterman-Reingold) positions, deterministic for a
    given graph: linked nodes pull together, all nodes push apart, and nodes
    with no links are spread on a ring around the connected cluster instead of
    piling up. Returns [(x, y), ...] scaled to roughly [-1, 1]."""
    import numpy as np
    if n == 0:
        return []
    if n == 1:
        return [(0.0, 0.0)]
    rng = np.random.default_rng(seed)
    pos = rng.uniform(-1, 1, size=(n, 2))
    pairs = sorted({(min(e["source_idx"], e["target_idx"]), max(e["source_idx"], e["target_idx"]))
                    for e in edges if e["source_idx"] != e["target_idx"]})
    linked = {i for pair in pairs for i in pair}
    k = 1.0 / np.sqrt(n)
    temp = 0.2
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.maximum(np.linalg.norm(delta, axis=2), 1e-3)
        force = (delta / dist[..., None]) * ((k * k) / dist)[..., None]
        disp = force.sum(axis=1)
        for a, b in pairs:
            d = pos[a] - pos[b]
            dl = max(float(np.linalg.norm(d)), 1e-3)
            pull = (d / dl) * (dl * dl / k)
            disp[a] -= pull
            disp[b] += pull
        disp -= pos * 4.0 * k          # gravity: keeps separate groups from drifting apart
        length = np.maximum(np.linalg.norm(disp, axis=1), 1e-9)
        pos += (disp / length[:, None]) * np.minimum(length, temp)[:, None]
        temp = max(temp * 0.98, 0.002)
    # Centre and scale on the connected nodes only: isolated nodes get pushed
    # far out by the repulsion and would otherwise shrink the real cluster to a dot.
    anchor = sorted(linked) or list(range(n))
    pos -= pos[anchor].mean(axis=0)
    scale = float(np.abs(pos[anchor]).max()) or 1.0
    pos = pos / scale
    loose = [i for i in range(n) if i not in linked]
    if loose and linked:
        import math
        ring = 1.25
        for j, i in enumerate(loose):
            ang = 2 * math.pi * j / len(loose)
            pos[i] = (ring * math.cos(ang), ring * math.sin(ang))
    return [(float(x), float(y)) for x, y in pos]


_TYPE_COLORS = {
    "concept":  "#58a6ff",
    "method":   "#3fb950",
    "dataset":  "#d29922",
    "metric":   "#a371f7",
    "problem":  "#f85149",
    "domain":   "#79c0ff",
    "model":    "#ffa657",
}
_EXTRA_PALETTE = ["#e0678f", "#2aa7a1", "#8e6bd1", "#c2873a", "#4f7fd6", "#7fa83f",
                  "#d6544f", "#3d9bd1", "#b05fb0", "#8a8f3a", "#d98e2b", "#5a7d8c",
                  "#c94f7c", "#38a36a", "#6a63c9", "#a8744f"]


def node_color(entity_type) -> str:
    """Models invent types ("disease", "biomarker"); give each a stable colour
    of its own rather than one shared grey."""
    t = str(entity_type or "concept")
    if t in _TYPE_COLORS:
        return _TYPE_COLORS[t]
    return _EXTRA_PALETTE[sum(map(ord, t)) % len(_EXTRA_PALETTE)]


def prepare_network_diagram_data(graph_data: dict) -> dict:
    """
    Prepare node/edge data for plotly network diagram.
    Returns a dict ready for the UI to render.
    """
    entities = graph_data.get("entities", [])
    relationships = graph_data.get("relationships", [])
    _color = node_color

    # Build id/name → index map. LLMs sometimes use entity names in relationships.
    id_to_idx = {e.get("id", e.get("name", f"e{i}")): i for i, e in enumerate(entities)}
    name_to_idx = {str(e.get("name", "")).lower(): i for i, e in enumerate(entities)}

    nodes = [{
        "id":       e.get("id", f"e{i}"),
        "name":     e.get("name", "Unknown"),
        "type":     e.get("type", "concept"),
        "color":    _color(e.get("type", "concept")),
        "papers":   e.get("papers", []),
        "importance": e.get("importance", "low"),
        "size":     {"high": 20, "medium": 14, "low": 9}.get(e.get("importance", "low"), 9),
    } for i, e in enumerate(entities)]

    edges = []
    for rel in relationships:
        src = rel.get("source", "")
        tgt = rel.get("target", "")
        src_idx = id_to_idx.get(src, name_to_idx.get(str(src).lower()))
        tgt_idx = id_to_idx.get(tgt, name_to_idx.get(str(tgt).lower()))
        if src_idx is not None and tgt_idx is not None:
            edges.append({
                "source_idx": src_idx,
                "target_idx": tgt_idx,
                "relation":   rel.get("relation", ""),
                "evidence":   rel.get("evidence", ""),
                "paper":      rel.get("paper", ""),
                "relationship_id": rel.get("relationship_id"),
            })

    try:
        for nd, (x, y) in zip(nodes, layout_positions(len(nodes), edges)):
            nd["x"], nd["y"] = round(x, 4), round(y, 4)
    except Exception:
        pass        # the UI falls back to a circle when positions are absent
    return {"nodes": nodes, "edges": edges}


def build_knowledge_graph(wiki: dict, client, domain_config: dict = None, evidence_objects: dict = None) -> dict:
    # B13 fix: distinguish an outright failed LLM call from a genuine empty
    # extraction — see Story 1.3 / AD-4. Story 1.2 deliberately left
    # extract_entities_and_relations' LLMCallError uncaught for this to catch.
    try:
        graph_data  = extract_entities_and_relations(wiki, client, domain_config=domain_config,
                                                     evidence_objects=evidence_objects)
        diagnostics = {
            "used_fallback": bool(graph_data.get("_used_fallback")),
            "raw_response_preview": graph_data.get("_raw_response_preview", ""),
            "llm_entities": len(graph_data.get("entities", [])),
            "llm_relationships": len(graph_data.get("relationships", [])),
        }
        if not graph_data.get("entities"):
            graph_data = _fallback_graph_from_wiki(wiki)
            diagnostics["used_fallback"] = True
            diagnostics["fallback_reason"] = "LLM graph extraction returned no entities."
    except LLMCallError as e:
        graph_data = _fallback_graph_from_wiki(wiki)
        diagnostics = {
            "used_fallback": True,
            "raw_response_preview": "",
            "llm_entities": 0,
            "llm_relationships": 0,
            "fallback_reason": f"LLM call failed: {e.error.detail}",
            "fallback_kind": e.error.kind,
        }

    # B13 fix (review, 2026-08-04): community detection is its own independent
    # LLM call and can fail even when entity extraction just succeeded (e.g. a
    # rate limit that starts mid-run) — guard it directly rather than only
    # pre-emptively skipping it right after a *different* known failure. This
    # protects every path uniformly instead of just the extraction-failed one.
    try:
        communities = build_communities(graph_data, client)
    except LLMCallError:
        communities = []

    # Clinova Phase 4, Epic 4.4 (Scientific Lineage): assigns relationship_id
    # to every relationship (LLM path and fallback path both covered, since
    # this runs after graph_data settles either way), and -- when the
    # caller supplies this run's real evidence_objects (Stage 2C already
    # runs before Stage 3, app.py) -- links each relationship's free-text
    # "evidence" paraphrase to real Evidence Object ids.
    _assign_relationship_ids(graph_data)
    provenance_resolution = None
    if evidence_objects is not None:
        provenance_resolution = _link_relationship_evidence(graph_data, wiki, evidence_objects)

    orphans     = find_orphan_concepts(graph_data, wiki)
    bridges     = find_missing_bridges(graph_data, wiki)
    network     = prepare_network_diagram_data(graph_data)

    if provenance_resolution is not None:
        diagnostics["provenance_resolution"] = provenance_resolution

    return {
        "entities":       graph_data.get("entities", []),
        "relationships":  graph_data.get("relationships", []),
        "communities":    communities,
        "orphan_concepts": orphans,
        "missing_bridges": bridges,
        "network_data":   network,
        # NOTE: diagnostics["fallback_reason"]/["fallback_kind"] are only present
        # when used_fallback is True — use .get(), not direct indexing.
        "diagnostics":    diagnostics,
        "stats": {
            "entity_count":       len(graph_data.get("entities", [])),
            "relationship_count": len(graph_data.get("relationships", [])),
            "community_count":    len(communities),
            "orphan_count":       len(orphans),
            "bridge_count":       len(bridges),
        },
    }
