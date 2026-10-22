"""Knowledge graph built from QUOTED EVIDENCE rather than from the wiki's bullet lists.

Every relationship must cite one evidence item (by handle) that states it; the relationship then carries
that item's id and its verbatim quote, so any edge in the graph can be traced to a page of a paper.
Relationships that cite nothing real are dropped, never kept as paraphrase. Entity and relation types come
from a fixed list for the corpus (anything else is mapped to a general type, with the original kept).

Entities left without any relationship (orphans) get two chances: a deterministic pass that links entities
named together in the same evidence item, then one model call for what is still unlinked.
"""
from __future__ import annotations

import json
import re

from pipeline.gap_agents import _handle, _parse_list, _statement, build_brief
from utils.azure_client import LLMCallError, unwrap

GROUNDED_GRAPH_VERSION = 1

SCIENCE_ENTITY_TYPES = ("disease", "condition", "intervention", "target", "biomarker", "method", "model_system",
                        "organism", "dataset_or_cohort", "outcome_measure", "concept")
SCIENCE_RELATIONS = ("treats", "targets", "causes", "associated_with", "measured_by", "studied_in", "modeled_by",
                     "compared_with", "contradicts", "extends", "enables", "limited_by", "requires", "validated_on")
DEFAULT_TYPE, DEFAULT_RELATION = "concept", "associated_with"
MAX_ORPHAN_LINKS = 2
PER_PAPER_EVIDENCE = 45

_SYSTEM = """You build a knowledge graph from QUOTED EVIDENCE of research papers.

You receive evidence items, each with a handle like [E1a2b3c4d], what it states, and the verbatim quote it rests on.
Return ONLY JSON:
{{"entities": [{{"id": "snake_case_id", "name": "short specific name", "type": "<one of the types>", "importance": "high|medium|low"}}],
 "relationships": [{{"source": "entity_id", "target": "entity_id", "relation": "<one of the relations>", "evidence_ref": "E1a2b3c4d"}}]}}

Rules:
- ENTITY TYPES (use exactly these): {types}
- RELATIONS (use exactly these): {relations}
- Every relationship MUST cite, in evidence_ref, the ONE handle of the evidence item that states it. Never invent a handle. A relationship you cannot ground in an item is not allowed.
- Be thorough: give each paper at least 8 entities and aim for MORE relationships than entities (about 1.5 per entity). Most entities should take part in two or more relationships, not hang off a single one.
- Every entity must appear in at least one relationship.
- Include at least 5 relationships that connect entities from DIFFERENT papers (the same drug, gene, model system or outcome studied in two papers; a method one paper uses and another criticises). Cite the item that supports the link.
- Names are short and specific ("airway epithelial cells", not "the cells used in the study")."""

_LINK_SYSTEM = """You connect unlinked entities of a knowledge graph to the rest of it, using QUOTED EVIDENCE.

For each unlinked entity, return up to {n} relationships to entities that already exist, each citing the handle of one evidence item that states it. If no item supports a link, return nothing for that entity.
Return ONLY JSON: {{"relationships": [{{"source": "entity_id", "target": "entity_id", "relation": "<one of the relations>", "evidence_ref": "E1a2b3c4d"}}]}}
RELATIONS (use exactly these): {relations}"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:80]


def has_quoted_evidence(evidence_objects: dict | None) -> bool:
    return any((e.get("provenance") or {}).get("quote")
               for items in (evidence_objects or {}).values() for e in items)


def _clean_handle(value) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or ""))


class _Graph:
    def __init__(self, titles: dict, by_handle: dict):
        self.titles, self.by_handle = titles, by_handle
        self.entities: dict[str, dict] = {}
        self.relationships: list[dict] = []
        self.diag = {"relations_proposed": 0, "relations_kept": 0, "dropped_no_evidence": 0,
                     "dropped_bad_entity": 0, "types_normalised": 0, "relations_normalised": 0}
        self._seen: set = set()

    def add_entity(self, raw: dict) -> None:
        name = str(raw.get("name") or "").strip()
        eid = _slug(raw.get("id") or name)
        if not name or not eid or eid in self.entities:
            return
        etype = str(raw.get("type") or "").strip().lower()
        if etype not in SCIENCE_ENTITY_TYPES:
            self.diag["types_normalised"] += 1
            raw = {**raw, "type_original": etype or None}
            etype = DEFAULT_TYPE
        imp = str(raw.get("importance") or "medium").lower()
        self.entities[eid] = {"id": eid, "name": name[:140], "type": etype,
                              "importance": imp if imp in ("high", "medium", "low") else "medium",
                              "papers": [], **({"type_original": raw["type_original"]} if raw.get("type_original") else {})}

    def resolve(self, ref) -> str | None:
        ref = str(ref or "").strip()
        if _slug(ref) in self.entities:
            return _slug(ref)
        low = ref.lower()
        return next((eid for eid, e in self.entities.items() if e["name"].lower() == low), None)

    def add_relationship(self, raw: dict, linked_by: str = "model") -> bool:
        self.diag["relations_proposed"] += 1
        src, tgt = self.resolve(raw.get("source")), self.resolve(raw.get("target"))
        if not src or not tgt or src == tgt:
            self.diag["dropped_bad_entity"] += 1
            return False
        hit = self.by_handle.get(_clean_handle(raw.get("evidence_ref")))
        if hit is None:
            self.diag["dropped_no_evidence"] += 1                # cited nothing real: not kept as paraphrase
            return False
        paper_id, ev = hit
        relation = str(raw.get("relation") or "").strip().lower()
        extra = {}
        if relation not in SCIENCE_RELATIONS:
            self.diag["relations_normalised"] += 1
            extra["relation_original"] = relation or None
            relation = DEFAULT_RELATION
        key = (src, tgt, relation, ev.get("evidence_id"))
        if key in self._seen:
            return False
        self._seen.add(key)
        prov = ev.get("provenance") or {}
        self.relationships.append({
            "source": src, "target": tgt, "relation": relation, "paper": self.titles.get(paper_id, paper_id),
            "paper_id": paper_id, "evidence": prov.get("quote") or _statement(ev),
            "evidence_ref": _handle(ev), "provenance_evidence_ids": [ev.get("evidence_id")],
            "page": prov.get("page"), "grounded": True, "linked_by": linked_by, **extra,
        })
        self.diag["relations_kept"] += 1
        return True

    def degree(self) -> dict:
        deg = {eid: 0 for eid in self.entities}
        for r in self.relationships:
            deg[r["source"]] += 1
            deg[r["target"]] += 1
        return deg

    def orphans(self) -> list[str]:
        return [eid for eid, n in self.degree().items() if n == 0]

    def finish(self) -> dict:
        for r in self.relationships:
            for eid in (r["source"], r["target"]):
                if r["paper"] not in self.entities[eid]["papers"]:
                    self.entities[eid]["papers"].append(r["paper"])
        return {"entities": list(self.entities.values()), "relationships": self.relationships}


def _name_in(text: str, name: str) -> bool:
    return len(name) >= 4 and re.search(r"(?<![a-z0-9])" + re.escape(name.lower()) + r"(?![a-z0-9])", text.lower()) is not None


def _link_by_comention(g: _Graph) -> int:
    """Orphans named in the same evidence item as another entity are linked through that item."""
    linked = 0
    items = [(h, pid, ev) for h, (pid, ev) in g.by_handle.items()]
    for oid in g.orphans():
        oname = g.entities[oid]["name"]
        made = 0
        for h, pid, ev in items:
            if made >= MAX_ORPHAN_LINKS:
                break
            text = f"{_statement(ev)} {(ev.get('provenance') or {}).get('quote') or ''}"
            if not _name_in(text, oname):
                continue
            for other_id, other in g.entities.items():
                if other_id != oid and _name_in(text, other["name"]):
                    if g.add_relationship({"source": oid, "target": other_id, "relation": DEFAULT_RELATION,
                                           "evidence_ref": h}, linked_by="co-mention"):
                        made += 1
                        linked += 1
                    break
    return linked


def extract_graph_grounded(evidence_objects: dict, wiki: dict, client) -> tuple[dict, dict]:
    """(graph_data, diagnostics). Raises LLMCallError if the first model call fails (the caller falls back)."""
    from pipeline.gap_agents import _titles
    titles = _titles(wiki, evidence_objects)
    brief, by_handle = build_brief(evidence_objects, {}, titles, per_paper_limit=PER_PAPER_EVIDENCE)
    system = _SYSTEM.format(types=", ".join(SCIENCE_ENTITY_TYPES), relations=", ".join(SCIENCE_RELATIONS))
    raw = unwrap(client.chat_json(system, "EVIDENCE:\n" + brief, max_tokens=16000))
    entities = _parse_list(raw, "entities") or []
    relationships = _parse_list(raw, "relationships") or []

    g = _Graph(titles, by_handle)
    for e in entities:
        g.add_entity(e)
    for r in relationships:
        g.add_relationship(r)
    diag = {"grounded": True, "grounded_version": GROUNDED_GRAPH_VERSION, "entities_proposed": len(g.entities)}
    first = g.orphans()
    diag["orphans_after_extraction"] = len(first)

    diag["linked_by_comention"] = _link_by_comention(g)
    remaining = g.orphans()
    diag["linked_by_model"] = 0
    if remaining:
        try:
            listing = [{"id": eid, "name": g.entities[eid]["name"], "type": g.entities[eid]["type"]} for eid in remaining]
            others = [{"id": eid, "name": e["name"]} for eid, e in g.entities.items() if eid not in remaining]
            user = (f"UNLINKED ENTITIES:\n{json.dumps(listing, ensure_ascii=False)}\n\n"
                    f"EXISTING ENTITIES:\n{json.dumps(others, ensure_ascii=False)}\n\nEVIDENCE:\n{brief}")
            raw2 = unwrap(client.chat_json(_LINK_SYSTEM.format(n=MAX_ORPHAN_LINKS, relations=", ".join(SCIENCE_RELATIONS)),
                                           user, max_tokens=6000))
            before = len(g.relationships)
            for r in _parse_list(raw2, "relationships") or []:
                if g.resolve(r.get("source")) in remaining or g.resolve(r.get("target")) in remaining:
                    g.add_relationship(r, linked_by="model-link")
            diag["linked_by_model"] = len(g.relationships) - before
        except LLMCallError as e:
            diag["orphan_link_error"] = f"model call failed: {e.error.kind}"

    graph = g.finish()
    left = g.orphans()
    n = max(1, len(g.entities))
    diag.update(g.diag)
    deg = g.degree()
    diag.update({"orphans_remaining": len(left), "orphan_share": round(len(left) / n, 3), "orphan_ids": left,
                 "leaf_share": round(sum(1 for v in deg.values() if v <= 1) / n, 3),     # entities hanging off one edge
                 "cross_paper_relations": sum(1 for r in g.relationships
                                              if len(set(g.entities[r["source"]]["papers"]) | set(g.entities[r["target"]]["papers"])) > 1)})
    for e in graph["entities"]:
        e["orphan"] = e["id"] in left
    return graph, diag
